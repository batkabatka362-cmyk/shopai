"""Intention tracker — declared 'I will do X' vs 'did X happen'.

Brains drift between plans and execution. `goal_compiler` turns goals
into runnable units; `commitment_register` tracks explicit
commitments. Neither measures whether stated *intentions* (less
formal than goals, more public than habits) were followed through.

Each intention has:

  • statement      — human-readable "I will scale ad to $50 by end of day"
  • due_ts         — deadline (seconds-from-epoch)
  • observable_kpi — optional KPI that determines completion
  • expected_value — value that completion implies
  • status         — pending | fulfilled | abandoned | expired

``resolve(id, observed_kpi_value)`` scores completion:

  * fulfilled  — observable target met before deadline
  * expired    — past deadline without completion
  * abandoned  — operator explicit cancel

Queries surface follow-through rate and stale intentions. Pure
stdlib, SQLite-persisted, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.intention_tracker")


Status = Literal["pending", "fulfilled", "abandoned", "expired"]


@dataclass
class Intention:
    id: str
    statement: str
    due_ts: float
    observable_kpi: str
    expected_value: float | None
    direction: str                 # "above" | "below" | "equals"
    status: Status
    created_ts: float
    resolved_ts: float | None = None
    observed_value: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.direction not in ("above", "below", "equals", ""):
            raise ValueError(
                "direction must be above|below|equals",
            )
        if self.status not in (
            "pending", "fulfilled", "abandoned", "expired",
        ):
            raise ValueError(
                "status must be pending|fulfilled|abandoned|expired",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "due_ts": self.due_ts,
            "observable_kpi": self.observable_kpi,
            "expected_value": self.expected_value,
            "direction": self.direction,
            "status": self.status,
            "created_ts": self.created_ts,
            "resolved_ts": self.resolved_ts,
            "observed_value": self.observed_value,
            "note": self.note,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS intentions (
    id              TEXT PRIMARY KEY,
    statement       TEXT NOT NULL,
    due_ts          REAL NOT NULL,
    observable_kpi  TEXT NOT NULL,
    expected_value  TEXT,
    direction       TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_ts      REAL NOT NULL,
    resolved_ts     REAL,
    observed_value  TEXT,
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_int_status
    ON intentions(status);
CREATE INDEX IF NOT EXISTS idx_int_due
    ON intentions(due_ts);
"""


class IntentionTracker:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, Intention] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT id, statement, due_ts, observable_kpi, "
                "expected_value, direction, status, created_ts, "
                "resolved_ts, observed_value, note FROM intentions",
            ):
                try:
                    expected = (
                        json.loads(row[4])
                        if row[4] is not None else None
                    )
                    observed = (
                        json.loads(row[9])
                        if row[9] is not None else None
                    )
                except (json.JSONDecodeError, ValueError):
                    expected, observed = None, None
                self._items[row[0]] = Intention(
                    id=row[0],
                    statement=row[1],
                    due_ts=float(row[2]),
                    observable_kpi=row[3],
                    expected_value=expected,
                    direction=row[5],
                    status=row[6],
                    created_ts=float(row[7]),
                    resolved_ts=(
                        float(row[8]) if row[8] is not None else None
                    ),
                    observed_value=observed,
                    note=row[10] or "",
                )

    def _persist(self, i: Intention) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO intentions("
            "  id, statement, due_ts, observable_kpi, "
            "  expected_value, direction, status, "
            "  created_ts, resolved_ts, observed_value, note"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                i.id, i.statement, i.due_ts, i.observable_kpi,
                (
                    json.dumps(i.expected_value)
                    if i.expected_value is not None else None
                ),
                i.direction, i.status, i.created_ts,
                i.resolved_ts,
                (
                    json.dumps(i.observed_value)
                    if i.observed_value is not None else None
                ),
                i.note,
            ),
        )
        self._conn.commit()

    # ── Declare ──────────────────────────────────────────

    def declare(
        self,
        *,
        statement: str,
        due_ts: float,
        observable_kpi: str = "",
        expected_value: float | None = None,
        direction: str = "",
        note: str = "",
    ) -> Intention:
        if not statement:
            raise ValueError("statement required")
        if due_ts <= time.time():
            raise ValueError(
                "due_ts must be in the future",
            )
        if expected_value is not None and not direction:
            raise ValueError(
                "direction required when expected_value given",
            )
        i = Intention(
            id=uuid.uuid4().hex,
            statement=str(statement),
            due_ts=float(due_ts),
            observable_kpi=str(observable_kpi or ""),
            expected_value=(
                float(expected_value)
                if expected_value is not None else None
            ),
            direction=direction or "",
            status="pending",
            created_ts=time.time(),
            note=str(note),
        )
        with self._lock:
            self._items[i.id] = i
            self._persist(i)
        return i

    # ── Resolve ──────────────────────────────────────────

    def resolve(
        self,
        intention_id: str,
        *,
        observed_value: float,
        ts: float | None = None,
    ) -> Intention:
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            i = self._items.get(intention_id)
            if i is None:
                raise ValueError(
                    f"unknown intention {intention_id!r}",
                )
            if i.status != "pending":
                raise ValueError(
                    f"intention already {i.status}",
                )
            i.observed_value = float(observed_value)
            i.resolved_ts = timestamp
            if i.expected_value is None:
                i.status = "fulfilled"
            elif timestamp > i.due_ts:
                i.status = "expired"
            else:
                ok = False
                if i.direction == "above":
                    ok = observed_value >= i.expected_value
                elif i.direction == "below":
                    ok = observed_value <= i.expected_value
                elif i.direction == "equals":
                    ok = abs(
                        observed_value - i.expected_value,
                    ) < 1e-6
                i.status = "fulfilled" if ok else "expired"
            self._persist(i)
            return i

    def abandon(
        self, intention_id: str, *, note: str = "",
    ) -> Intention:
        with self._lock:
            i = self._items.get(intention_id)
            if i is None:
                raise ValueError(
                    f"unknown intention {intention_id!r}",
                )
            if i.status != "pending":
                raise ValueError(
                    f"intention already {i.status}",
                )
            i.status = "abandoned"
            i.resolved_ts = time.time()
            if note:
                i.note = note
            self._persist(i)
            return i

    def expire_overdue(
        self, *, now: float | None = None,
    ) -> int:
        at = float(now if now is not None else time.time())
        n = 0
        with self._lock:
            for i in self._items.values():
                if (
                    i.status == "pending"
                    and at > i.due_ts
                ):
                    i.status = "expired"
                    i.resolved_ts = at
                    self._persist(i)
                    n += 1
        return n

    # ── Queries ──────────────────────────────────────────

    def get(self, intention_id: str) -> Intention | None:
        with self._lock:
            return self._items.get(intention_id)

    def pending(self) -> list[Intention]:
        with self._lock:
            return [
                i for i in self._items.values()
                if i.status == "pending"
            ]

    def by_status(
        self, status: Status,
    ) -> list[Intention]:
        with self._lock:
            return [
                i for i in self._items.values()
                if i.status == status
            ]

    def follow_through_rate(self) -> float:
        with self._lock:
            resolved = [
                i for i in self._items.values()
                if i.status in ("fulfilled", "expired", "abandoned")
            ]
            if not resolved:
                return 0.0
            fulfilled = sum(
                1 for i in resolved if i.status == "fulfilled"
            )
            return fulfilled / len(resolved)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_status: dict[str, int] = {}
            for i in self._items.values():
                by_status[i.status] = (
                    by_status.get(i.status, 0) + 1
                )
            return {
                "total": len(self._items),
                "by_status": by_status,
                "follow_through_rate": round(
                    self.follow_through_rate(), 4,
                ),
            }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
