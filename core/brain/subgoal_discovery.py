"""Subgoal discovery — extract reusable sub-patterns from achieved goals.

The hierarchical planner (v4) decomposes *one* goal into subgoals
per invocation. goal_agenda (v6-D1) tracks current goals. Neither
looks *across* completed goals to find recurring sub-sequences
that could become named reusable building blocks.

SubgoalDiscovery scans achieved goal traces — each trace is an
ordered list of ``Step(kind, params)`` entries — and surfaces
common sub-sequences. Promoted subgoals get a stable id and a
success-rate posterior so the planner can later splice them in
instead of re-deriving from scratch.

Algorithm (deterministic, O(N × K²) for N traces of length K):

  1. Canonicalise each step to ``kind|sorted_params_hash``.
  2. Sliding window over every trace of length 2..``max_len``
     (default 4).
  3. Count frequencies across traces (not within) — avoid one
     noisy trace inflating the count.
  4. Emit subgoals whose cross-trace support ≥ ``min_support``
     (default 3) AND whose success correlation is positive.

SubgoalLibrary stores promotions and tracks *actual* application
success separately so the discovery signal is decoupled from the
production signal.

Persistence: ``data/subgoals.db``. Pure Python.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/subgoals.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subgoals (
    id              TEXT PRIMARY KEY,
    signature       TEXT UNIQUE NOT NULL,
    pattern_json    TEXT NOT NULL,
    description     TEXT,
    support         INTEGER NOT NULL DEFAULT 0,
    win_rate        REAL NOT NULL DEFAULT 0.5,
    applications    INTEGER NOT NULL DEFAULT 0,
    successes       INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_support ON subgoals(support DESC);
"""


@dataclass
class Step:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def canonical(self) -> str:
        items = sorted((k, str(v)) for k, v in self.params.items())
        h = hashlib.sha1(
            json.dumps(items).encode("utf-8"),
        ).hexdigest()[:8]
        return f"{self.kind}|{h}"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": self.params}


@dataclass
class Trace:
    trace_id: str
    steps: list[Step]
    succeeded: bool = True

    def canonical(self) -> list[str]:
        return [s.canonical() for s in self.steps]


@dataclass
class Subgoal:
    id: str
    signature: str
    pattern: list[Step]
    description: str = ""
    support: int = 0
    win_rate: float = 0.5
    applications: int = 0
    successes: int = 0
    created_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "pattern": [s.as_dict() for s in self.pattern],
            "description": self.description,
            "support": self.support,
            "win_rate": round(self.win_rate, 3),
            "applications": self.applications,
            "successes": self.successes,
            "created_at": self.created_at,
        }


# ── Discovery engine ────────────────────────────────────────

def _subsequences(
    items: list[str], min_len: int, max_len: int,
) -> Iterable[tuple[str, ...]]:
    for n in range(min_len, min(max_len, len(items)) + 1):
        for i in range(len(items) - n + 1):
            yield tuple(items[i:i + n])


def discover(
    traces: Iterable[Trace],
    *,
    min_support: int = 3,
    min_len: int = 2,
    max_len: int = 4,
) -> list[tuple[tuple[str, ...], int, float]]:
    """Return (signature_tuple, cross_trace_support, win_rate)
    candidates above threshold."""
    traces = list(traces)
    if len(traces) < min_support:
        return []
    # For each sub-sequence, record which trace_ids contained it
    trace_sets: dict[tuple[str, ...], set[str]] = defaultdict(set)
    trace_wins: dict[tuple[str, ...], int] = defaultdict(int)
    for tr in traces:
        canon = tr.canonical()
        seen_in_trace: set[tuple[str, ...]] = set()
        for sub in _subsequences(canon, min_len, max_len):
            seen_in_trace.add(sub)
        for sub in seen_in_trace:
            trace_sets[sub].add(tr.trace_id)
            if tr.succeeded:
                trace_wins[sub] += 1
    out: list[tuple[tuple[str, ...], int, float]] = []
    for sub, ids in trace_sets.items():
        support = len(ids)
        if support < min_support:
            continue
        win_rate = trace_wins[sub] / support
        # Only keep positively correlated sub-sequences
        if win_rate < 0.5:
            continue
        out.append((sub, support, win_rate))
    out.sort(key=lambda x: (-x[1], -x[2]))
    return out


# ── Library ─────────────────────────────────────────────────

class SubgoalLibrary:
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

    # ── Promotion ───────────────────────────────────────────

    def promote(
        self,
        pattern: list[Step],
        support: int,
        win_rate: float,
        description: str = "",
    ) -> Subgoal:
        sig = "|".join(s.canonical() for s in pattern)
        sid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            # Upsert by signature
            existing = conn.execute(
                "SELECT id FROM subgoals WHERE signature=?", (sig,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE subgoals SET support=?, win_rate=?, "
                    "description=? WHERE signature=?",
                    (int(support), float(win_rate),
                     description, sig),
                )
                sid = existing[0]
            else:
                conn.execute(
                    "INSERT INTO subgoals (id, signature, pattern_json, "
                    "description, support, win_rate, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (sid, sig,
                     json.dumps([s.as_dict() for s in pattern]),
                     description, int(support), float(win_rate), now),
                )
            conn.commit()
        return self.get(sid)

    def get(self, sid: str) -> Subgoal | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, signature, pattern_json, description, "
                "support, win_rate, applications, successes, created_at "
                "FROM subgoals WHERE id=?",
                (sid,),
            ).fetchone()
        return _row_to_subgoal(row) if row else None

    # ── Application ────────────────────────────────────────

    def record_application(
        self, sid: str, success: bool,
    ) -> Subgoal | None:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE subgoals SET applications=applications+1, "
                "successes=successes + ? WHERE id=?",
                (1 if success else 0, sid),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get(sid)

    # ── Listings ───────────────────────────────────────────

    def top(self, k: int = 10) -> list[Subgoal]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, signature, pattern_json, description, "
                "support, win_rate, applications, successes, created_at "
                "FROM subgoals ORDER BY support DESC, win_rate DESC "
                "LIMIT ?",
                (int(k),),
            ).fetchall()
        return [_row_to_subgoal(r) for r in rows]

    def size(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM subgoals"
            ).fetchone()
        return int(row[0]) if row else 0


def _row_to_subgoal(row: tuple) -> Subgoal:
    pattern = [
        Step(kind=p["kind"], params=p.get("params", {}))
        for p in json.loads(row[2] or "[]")
    ]
    return Subgoal(
        id=row[0],
        signature=row[1],
        pattern=pattern,
        description=row[3] or "",
        support=int(row[4] or 0),
        win_rate=float(row[5] or 0.5),
        applications=int(row[6] or 0),
        successes=int(row[7] or 0),
        created_at=float(row[8] or 0),
    )


# ── One-shot helper ─────────────────────────────────────────

def discover_and_promote(
    traces: Iterable[Trace],
    library: SubgoalLibrary,
    *,
    min_support: int = 3,
    min_len: int = 2,
    max_len: int = 4,
) -> int:
    """Run discovery and promote each candidate into the library.
    Returns the count promoted."""
    traces = list(traces)
    candidates = discover(
        traces, min_support=min_support,
        min_len=min_len, max_len=max_len,
    )
    # Map canonical string → original Steps so we can re-hydrate.
    canon_to_steps: dict[str, Step] = {}
    for tr in traces:
        for s in tr.steps:
            canon_to_steps.setdefault(s.canonical(), s)
    count = 0
    for sig_tuple, support, win_rate in candidates:
        pattern = [
            canon_to_steps[c] for c in sig_tuple
            if c in canon_to_steps
        ]
        if len(pattern) != len(sig_tuple):
            continue
        library.promote(pattern, support=support, win_rate=win_rate)
        count += 1
    return count
