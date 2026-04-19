"""Regret minimizer — track 'what we should have done' and bias future.

The counterfactual engine (v3) computes regret *for one* decision
retrospectively. Without a running regret tracker, the brain
never adjusts future behaviour to minimise it — it re-commits the
same missed-opportunity error every cycle.

RegretMinimizer maintains a running ledger of (context_signature,
chosen_action, realised_outcome, best_alternative_outcome) rows.
Every entry's regret is ``best_alternative − realised``. From
that:

  • running total regret per signature
  • running total regret per action
  • advice() returns an ``Advice`` with suggested action biases
    the planner / dual-process arbiter can consume to prefer
    lower-regret branches.

Decisions *match* on their context signature (compiled via
context_compiler v12-D4). Counterfactual enrichment comes from
world_model predictions or explicit alternatives the caller passed
in.

Persistence: ``data/regret.db``. SQLite, thread-safe, zero LLM.

Advice weights stay bounded — a single extreme outcome can't
dominate; the bias is a softmax over normalised total regret.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/regret.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id              TEXT PRIMARY KEY,
    created_at      REAL NOT NULL,
    signature       TEXT NOT NULL,
    chosen_action   TEXT NOT NULL,
    realised        REAL NOT NULL,
    counterfactual  REAL NOT NULL,
    regret          REAL NOT NULL,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_sig ON entries(signature);
CREATE INDEX IF NOT EXISTS idx_action ON entries(chosen_action);
"""


@dataclass
class RegretEntry:
    id: str
    created_at: float
    signature: str
    chosen_action: str
    realised: float
    counterfactual: float
    regret: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "signature": self.signature,
            "chosen_action": self.chosen_action,
            "realised": round(self.realised, 3),
            "counterfactual": round(self.counterfactual, 3),
            "regret": round(self.regret, 3),
            "note": self.note,
        }


@dataclass
class Advice:
    signature: str
    biases: dict[str, float] = field(default_factory=dict)
    total_regret: float = 0.0
    entries: int = 0

    def top_action(self) -> str | None:
        if not self.biases:
            return None
        return max(self.biases.keys(), key=lambda k: self.biases[k])

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "biases": {k: round(v, 3) for k, v in self.biases.items()},
            "total_regret": round(self.total_regret, 3),
            "entries": self.entries,
            "top_action": self.top_action(),
        }


# ── Minimizer ───────────────────────────────────────────────

class RegretMinimizer:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Record ─────────────────────────────────────────────

    def record(
        self,
        signature: str,
        chosen_action: str,
        realised: float,
        counterfactual: float,
        note: str = "",
    ) -> RegretEntry:
        """Store one (context, chosen, realised, counterfactual)
        row. regret = counterfactual − realised (positive regret =
        we should have done better)."""
        signature = signature.strip()
        chosen_action = chosen_action.strip()
        if not signature or not chosen_action:
            raise ValueError("signature and chosen_action required")
        entry = RegretEntry(
            id=uuid.uuid4().hex,
            created_at=time.time(),
            signature=signature,
            chosen_action=chosen_action,
            realised=float(realised),
            counterfactual=float(counterfactual),
            regret=float(counterfactual) - float(realised),
            note=note,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO entries (id, created_at, signature, "
                "chosen_action, realised, counterfactual, regret, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (entry.id, entry.created_at, entry.signature,
                 entry.chosen_action, entry.realised,
                 entry.counterfactual, entry.regret, entry.note),
            )
            conn.commit()
        return entry

    # ── Advice ─────────────────────────────────────────────

    def advise(
        self, signature: str, *,
        actions: Iterable[str] | None = None,
        limit: int = 200,
    ) -> Advice:
        """Returns softmax-weighted action biases over the per-
        signature regret history.

        High cumulative regret for an action → lower bias.
        Actions never logged get a neutral bias of 0 (caller should
        interpret as 'no preference'). When ``actions`` is supplied
        the returned map always covers each one (with 0 as default).
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chosen_action, regret FROM entries "
                "WHERE signature=? ORDER BY created_at DESC LIMIT ?",
                (signature.strip(), int(limit)),
            ).fetchall()
        totals: dict[str, float] = {}
        count = 0
        for action, regret in rows:
            totals[action] = totals.get(action, 0.0) + float(regret)
            count += 1
        if actions:
            for a in actions:
                totals.setdefault(a, 0.0)
        # Convert cumulative regret → bias via negative softmax
        # (lower regret should be favoured).
        biases: dict[str, float] = {}
        if totals:
            neg = {k: -v for k, v in totals.items()}
            # Subtract max for numerical stability
            m = max(neg.values())
            exps = {k: math.exp(v - m) for k, v in neg.items()}
            z = sum(exps.values())
            biases = {k: v / z for k, v in exps.items()} if z > 0 else {
                k: 1.0 / len(totals) for k in totals
            }
        return Advice(
            signature=signature,
            biases=biases,
            total_regret=sum(totals.values()),
            entries=count,
        )

    # ── Introspection ─────────────────────────────────────

    def top_regretted(self, k: int = 10) -> list[tuple[str, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT signature, SUM(regret) FROM entries "
                "GROUP BY signature ORDER BY SUM(regret) DESC LIMIT ?",
                (int(k),),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(regret), AVG(regret) FROM entries"
            ).fetchone()
        return {
            "total_entries": int(row[0] or 0),
            "cumulative_regret": round(float(row[1] or 0), 3),
            "avg_regret": round(float(row[2] or 0), 3),
        }

    def entries_for(
        self, signature: str, limit: int = 20,
    ) -> list[RegretEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, signature, chosen_action, "
                "realised, counterfactual, regret, note FROM entries "
                "WHERE signature=? ORDER BY created_at DESC LIMIT ?",
                (signature.strip(), int(limit)),
            ).fetchall()
        return [
            RegretEntry(
                id=r[0], created_at=float(r[1]),
                signature=r[2], chosen_action=r[3],
                realised=float(r[4]), counterfactual=float(r[5]),
                regret=float(r[6]), note=r[7] or "",
            )
            for r in rows
        ]


# ── Singleton ────────────────────────────────────────────────

_RM_LOCK = threading.Lock()
_RM: RegretMinimizer | None = None


def minimizer() -> RegretMinimizer:
    global _RM
    if _RM is None:
        with _RM_LOCK:
            if _RM is None:
                _RM = RegretMinimizer()
    return _RM
