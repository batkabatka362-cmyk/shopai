"""Rollout manager — canary → percentage → full rollout for policies.

self_improvement (v9) proposes a config change; policy_library
(v11) promotes a strategy; decision_governor (v12) enforces
whatever the library advises. Flipping the switch in one step
means a bad policy hits 100% of traffic on its first cycle.

RolloutManager adds gradual deployment. Each rollout goes
through stages:

  • canary  — exposed to a tiny pct (default 5%) for N cycles
  • ramp    — grows by step_pct each cycle if no rollback condition
  • full    — 100% exposure
  • halt    — rollback triggered, pct goes to 0

Stages advance when:

  1. min_cycles at the current pct have elapsed.
  2. observed success_rate ≥ ok_threshold.
  3. no rollback signal was flagged.

Rollback triggers when:

  • rollback_on_failure=True and observed failure rate exceeds
    fail_threshold.
  • an external signal calls rollback(rollout_id, reason).

Each rollout assigns a traffic split deterministically via a
hash-based bucketing so the same entity consistently sees the
same variant (sticky assignment).

Persistence: ``data/rollout.db`` SQLite. Thread-safe. No LLM.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


_DB_PATH = Path("data/rollout.db")

Stage = Literal["canary", "ramp", "full", "halt"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rollouts (
    id              TEXT PRIMARY KEY,
    created_at      REAL NOT NULL,
    name            TEXT NOT NULL,
    stage           TEXT NOT NULL DEFAULT 'canary',
    current_pct     REAL NOT NULL DEFAULT 5.0,
    step_pct        REAL NOT NULL DEFAULT 15.0,
    min_cycles      INTEGER NOT NULL DEFAULT 3,
    cycles_at_pct   INTEGER NOT NULL DEFAULT 0,
    ok_threshold    REAL NOT NULL DEFAULT 0.8,
    fail_threshold  REAL NOT NULL DEFAULT 0.3,
    successes       INTEGER NOT NULL DEFAULT 0,
    failures        INTEGER NOT NULL DEFAULT 0,
    halt_reason     TEXT,
    updated_at      REAL NOT NULL
);
"""


@dataclass
class Rollout:
    id: str
    created_at: float
    name: str
    stage: Stage
    current_pct: float
    step_pct: float
    min_cycles: int
    cycles_at_pct: int
    ok_threshold: float
    fail_threshold: float
    successes: int
    failures: int
    halt_reason: str = ""
    updated_at: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        if total == 0:
            return 0.0
        return self.successes / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "name": self.name,
            "stage": self.stage,
            "current_pct": round(self.current_pct, 2),
            "step_pct": self.step_pct,
            "min_cycles": self.min_cycles,
            "cycles_at_pct": self.cycles_at_pct,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "halt_reason": self.halt_reason,
            "updated_at": self.updated_at,
        }


# ── Manager ─────────────────────────────────────────────────

class RolloutManager:
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

    # ── Lifecycle ──────────────────────────────────────────

    def start(
        self,
        rollout_id: str,
        name: str,
        *,
        initial_pct: float = 5.0,
        step_pct: float = 15.0,
        min_cycles: int = 3,
        ok_threshold: float = 0.8,
        fail_threshold: float = 0.3,
    ) -> Rollout:
        rollout_id = rollout_id.strip()
        if not rollout_id:
            raise ValueError("rollout_id required")
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO rollouts "
                "(id, created_at, name, stage, current_pct, step_pct, "
                " min_cycles, cycles_at_pct, ok_threshold, "
                " fail_threshold, successes, failures, halt_reason, "
                " updated_at) "
                "VALUES (?,?,?, 'canary', ?, ?, ?, 0, ?, ?, 0, 0, "
                "        NULL, ?)",
                (rollout_id, now, name, float(initial_pct),
                 float(step_pct), int(min_cycles),
                 float(ok_threshold), float(fail_threshold), now),
            )
            conn.commit()
        return self.get(rollout_id)

    def rollback(
        self, rollout_id: str, reason: str = "",
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE rollouts SET stage='halt', current_pct=0, "
                "halt_reason=?, updated_at=? WHERE id=?",
                (reason, time.time(), rollout_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get(self, rollout_id: str) -> Rollout | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, name, stage, current_pct, "
                "step_pct, min_cycles, cycles_at_pct, ok_threshold, "
                "fail_threshold, successes, failures, halt_reason, "
                "updated_at FROM rollouts WHERE id=?",
                (rollout_id,),
            ).fetchone()
        return _row_to_rollout(row) if row else None

    def active(self) -> list[Rollout]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, name, stage, current_pct, "
                "step_pct, min_cycles, cycles_at_pct, ok_threshold, "
                "fail_threshold, successes, failures, halt_reason, "
                "updated_at FROM rollouts "
                "WHERE stage != 'halt' AND stage != 'full'"
            ).fetchall()
        return [_row_to_rollout(r) for r in rows]

    # ── Traffic assignment ────────────────────────────────

    def exposed(self, rollout_id: str, entity_id: str) -> bool:
        """True iff this entity falls within the current pct bucket."""
        r = self.get(rollout_id)
        if r is None or r.stage == "halt":
            return False
        if r.stage == "full":
            return True
        # Deterministic hash-bucketing into [0, 100)
        h = hashlib.md5(
            f"{rollout_id}|{entity_id}".encode(),
        ).hexdigest()
        bucket = int(h[:8], 16) % 10_000 / 100.0
        return bucket < r.current_pct

    # ── Outcome tracking ──────────────────────────────────

    def record_outcome(
        self, rollout_id: str, success: bool,
    ) -> Rollout | None:
        r = self.get(rollout_id)
        if r is None:
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE rollouts SET successes = successes + ?, "
                "failures = failures + ?, updated_at = ? WHERE id = ?",
                (1 if success else 0,
                 0 if success else 1,
                 time.time(), rollout_id),
            )
            conn.commit()
        return self.get(rollout_id)

    # ── Cycle tick ────────────────────────────────────────

    def tick(self, rollout_id: str) -> Rollout | None:
        r = self.get(rollout_id)
        if r is None or r.stage in ("halt", "full"):
            return r
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE rollouts SET cycles_at_pct = cycles_at_pct + 1 "
                "WHERE id=?",
                (rollout_id,),
            )
            conn.commit()
        r = self.get(rollout_id)
        # Evaluate rollback first
        if r.failures + r.successes >= 5 and r.success_rate < r.fail_threshold:
            self.rollback(rollout_id, reason="success rate below fail_threshold")
            return self.get(rollout_id)
        # Advance if min_cycles met and success_rate adequate
        if (r.cycles_at_pct >= r.min_cycles
                and r.success_rate >= r.ok_threshold):
            next_pct = min(100.0, r.current_pct + r.step_pct)
            next_stage: Stage = "full" if next_pct >= 100.0 else "ramp"
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE rollouts SET current_pct=?, stage=?, "
                    "cycles_at_pct=0, updated_at=? WHERE id=?",
                    (next_pct, next_stage, time.time(), rollout_id),
                )
                conn.commit()
        return self.get(rollout_id)


def _row_to_rollout(row: tuple) -> Rollout:
    return Rollout(
        id=row[0],
        created_at=float(row[1]),
        name=row[2] or "",
        stage=row[3] or "canary",
        current_pct=float(row[4] or 0),
        step_pct=float(row[5] or 15.0),
        min_cycles=int(row[6] or 3),
        cycles_at_pct=int(row[7] or 0),
        ok_threshold=float(row[8] or 0.8),
        fail_threshold=float(row[9] or 0.3),
        successes=int(row[10] or 0),
        failures=int(row[11] or 0),
        halt_reason=row[12] or "",
        updated_at=float(row[13] or 0),
    )
