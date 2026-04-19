"""Policy library — named strategy catalogue with applicability.

Skills (v3) tracked low-level atomic capabilities. Rules tracked
one-shot if-then triggers. Neither captured the *named strategic
patterns* operators actually reach for: "aggressive kill", "slow-
burn scale", "premium tone for luxury audio", "weekend
promotions". Without a catalogue, the brain rediscovers the same
shape every cycle.

PolicyLibrary stores named Policy entries with:

  • name              — stable human-readable id
  • description       — one-liner
  • applicability     — predicate dict of feature → expected values
  • action_template   — the shape of the action to run
  • success_count / use_count → Beta posterior on efficacy
  • evidence          — list of source event ids
  • tags              — free-form labels

APIs:

  register(name, description, applicability, action_template, tags?)
  propose(context) → list[(Policy, fit_score)] ranked by (fit ×
      success_rate) — the planner can pick the top-k
  record_outcome(name, success) — folds into the posterior
  retire(name, reason)          — manual off-switch
  top(k, min_uses)              — best-track-record policies
  find_similar(context, k)      — nearest match even when predicate
      doesn't fully hold

Persistence: ``data/policy_library.db``. Pure Python, zero LLM.
Policies can cite source rules, so abstraction_ladder (v9-D2) can
lift rules into policies and the library can cite back.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/policy_library.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    name             TEXT PRIMARY KEY,
    description      TEXT,
    applicability    TEXT NOT NULL,
    action_template  TEXT NOT NULL,
    tags             TEXT,
    created_at       REAL NOT NULL,
    success_count    INTEGER NOT NULL DEFAULT 0,
    use_count        INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',
    retire_reason    TEXT,
    evidence         TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON policies(status);
"""


@dataclass
class Policy:
    name: str
    description: str
    applicability: dict[str, Any]    # feature → expected value
    action_template: dict[str, Any]
    tags: tuple[str, ...] = ()
    created_at: float = 0.0
    success_count: int = 0
    use_count: int = 0
    status: str = "active"           # active | retired
    retire_reason: str = ""
    evidence: tuple[str, ...] = ()

    @property
    def success_rate(self) -> float:
        # Beta(1+s, 1+(u-s)) posterior mean
        alpha = 1.0 + self.success_count
        beta = 1.0 + max(0, self.use_count - self.success_count)
        return alpha / (alpha + beta)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "applicability": self.applicability,
            "action_template": self.action_template,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "success_count": self.success_count,
            "use_count": self.use_count,
            "success_rate": round(self.success_rate, 3),
            "status": self.status,
            "retire_reason": self.retire_reason,
            "evidence": list(self.evidence),
        }


@dataclass
class PolicyMatch:
    policy: Policy
    fit: float                        # 0-1, fraction of applicability
                                      # predicate values matching
    score: float                      # fit × success_rate

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.policy.name,
            "fit": round(self.fit, 3),
            "score": round(self.score, 3),
            "success_rate": round(self.policy.success_rate, 3),
        }


# ── Library ─────────────────────────────────────────────────

class PolicyLibrary:
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

    # ── Register ────────────────────────────────────────────

    def register(
        self,
        name: str,
        description: str,
        applicability: dict[str, Any],
        action_template: dict[str, Any],
        tags: Iterable[str] = (),
        evidence: Iterable[str] = (),
    ) -> Policy:
        name = name.strip()
        if not name:
            raise ValueError("name required")
        p = Policy(
            name=name,
            description=description.strip(),
            applicability=dict(applicability),
            action_template=dict(action_template),
            tags=tuple(tags),
            created_at=time.time(),
            evidence=tuple(evidence),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO policies "
                "(name, description, applicability, action_template, "
                " tags, created_at, success_count, use_count, status, "
                " retire_reason, evidence) "
                "VALUES (?,?,?,?,?,?,0,0,'active','',?)",
                (p.name, p.description,
                 json.dumps(p.applicability, default=str),
                 json.dumps(p.action_template, default=str),
                 json.dumps(list(p.tags)),
                 p.created_at,
                 json.dumps(list(p.evidence))),
            )
            conn.commit()
        return p

    def get(self, name: str) -> Policy | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM policies WHERE name=?", (name,),
            ).fetchone()
        return _row_to_policy(row) if row else None

    # ── Outcome recording ──────────────────────────────────

    def record_outcome(self, name: str, success: bool) -> Policy | None:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE policies SET "
                "  use_count = use_count + 1, "
                "  success_count = success_count + ? "
                "WHERE name=? AND status='active'",
                (1 if success else 0, name),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get(name)

    # ── Retire ──────────────────────────────────────────────

    def retire(self, name: str, reason: str = "") -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE policies SET status='retired', retire_reason=? "
                "WHERE name=? AND status='active'",
                (reason, name),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Proposal ───────────────────────────────────────────

    def propose(
        self,
        context: dict[str, Any],
        top_k: int = 5,
        min_fit: float = 0.5,
    ) -> list[PolicyMatch]:
        """Return policies whose applicability fits the context, ranked
        by fit × success_rate."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM policies WHERE status='active'"
            ).fetchall()
        matches: list[PolicyMatch] = []
        for row in rows:
            p = _row_to_policy(row)
            fit = _predicate_fit(p.applicability, context)
            if fit < min_fit:
                continue
            matches.append(PolicyMatch(
                policy=p, fit=fit,
                score=fit * p.success_rate,
            ))
        matches.sort(key=lambda m: -m.score)
        return matches[:top_k]

    def find_similar(
        self, context: dict[str, Any], k: int = 3,
    ) -> list[PolicyMatch]:
        """Relaxed proposal: no minimum fit, rank purely by fit even
        when the predicate doesn't fully hold."""
        return self.propose(context, top_k=k, min_fit=0.0)

    # ── Introspection ──────────────────────────────────────

    def top(self, k: int = 5, min_uses: int = 3) -> list[Policy]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM policies WHERE status='active' "
                "AND use_count >= ?",
                (int(min_uses),),
            ).fetchall()
        ps = [_row_to_policy(r) for r in rows]
        ps.sort(key=lambda p: -p.success_rate)
        return ps[:k]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            by = conn.execute(
                "SELECT status, COUNT(*) FROM policies GROUP BY status"
            ).fetchall()
            uses = conn.execute(
                "SELECT SUM(use_count), SUM(success_count) FROM policies"
            ).fetchone()
        return {
            "counts": {s: int(c) for s, c in by},
            "total_uses": int(uses[0] or 0),
            "total_successes": int(uses[1] or 0),
        }


def _predicate_fit(
    applicability: dict[str, Any], context: dict[str, Any],
) -> float:
    if not applicability:
        return 1.0   # policy always applies
    matched = 0
    for k, v in applicability.items():
        ctx_v = context.get(k)
        if ctx_v is None:
            continue
        if _matches_predicate(v, ctx_v):
            matched += 1
    return matched / len(applicability)


def _matches_predicate(expected: Any, observed: Any) -> bool:
    """True iff ``observed`` satisfies ``expected``.

    ``expected`` may be a literal, a list of acceptable values, or
    a range dict ``{"gt": x, "lt": y}``."""
    if isinstance(expected, list):
        return observed in expected
    if isinstance(expected, dict):
        try:
            if "gt" in expected and not (float(observed) > float(expected["gt"])):
                return False
            if "ge" in expected and not (float(observed) >= float(expected["ge"])):
                return False
            if "lt" in expected and not (float(observed) < float(expected["lt"])):
                return False
            if "le" in expected and not (float(observed) <= float(expected["le"])):
                return False
        except (TypeError, ValueError):
            return False
        return True
    return observed == expected


def _row_to_policy(row: tuple) -> Policy:
    return Policy(
        name=row[0],
        description=row[1] or "",
        applicability=_loads(row[2], {}),
        action_template=_loads(row[3], {}),
        tags=tuple(_loads(row[4], [])),
        created_at=float(row[5] or 0),
        success_count=int(row[6] or 0),
        use_count=int(row[7] or 0),
        status=row[8] or "active",
        retire_reason=row[9] or "",
        evidence=tuple(_loads(row[10], [])),
    )


def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return default
