"""Assumption ledger — explicit hypotheses, tested against outcomes.

Most decisions rest on implicit assumptions ("CPM stays under $25",
"buyer picks the cheaper variant"). When outcomes diverge from
expectations we blame noise because the assumption was never written
down. assumption_ledger makes this explicit.

For every decision, callers log assumptions via ``assume(...)``.
Each assumption has:

  • id
  • statement (what we think is true)
  • related_decision_id (optional — ties to a specific call)
  • kpi (optional — the metric that validates it)
  • expected_value (if kpi is set)
  • tolerance (±range for a "close enough" validation)
  • status: pending / validated / violated / abandoned

Later, ``validate(assumption_id, observed_value)`` compares observed
to expected ± tolerance. If the band is breached the assumption is
marked violated — ready to feed into self_revision_journal.

Pure stdlib, SQLite-persisted, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from utils.logger import get_logger


logger = get_logger("brain.assumption_ledger")


Status = Literal["pending", "validated", "violated", "abandoned"]


@dataclass
class Assumption:
    id: str
    statement: str
    related_decision_id: str
    kpi: str
    expected_value: float | None
    tolerance: float
    status: Status
    created_ts: float
    resolved_ts: float | None = None
    observed_value: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in (
            "pending", "validated", "violated", "abandoned",
        ):
            raise ValueError(
                "status must be pending|validated|violated|abandoned",
            )
        if self.tolerance < 0:
            raise ValueError("tolerance must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "related_decision_id": self.related_decision_id,
            "kpi": self.kpi,
            "expected_value": self.expected_value,
            "tolerance": round(self.tolerance, 6),
            "status": self.status,
            "created_ts": self.created_ts,
            "resolved_ts": self.resolved_ts,
            "observed_value": self.observed_value,
            "note": self.note,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS assumptions (
    id                  TEXT PRIMARY KEY,
    statement           TEXT NOT NULL,
    related_decision_id TEXT NOT NULL,
    kpi                 TEXT NOT NULL,
    expected_value      TEXT,
    tolerance           REAL NOT NULL,
    status              TEXT NOT NULL,
    created_ts          REAL NOT NULL,
    resolved_ts         REAL,
    observed_value      TEXT,
    note                TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_assume_status
    ON assumptions(status);
CREATE INDEX IF NOT EXISTS idx_assume_decision
    ON assumptions(related_decision_id);
"""


class AssumptionLedger:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, Assumption] = {}
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
                "SELECT id, statement, related_decision_id, kpi, "
                "expected_value, tolerance, status, created_ts, "
                "resolved_ts, observed_value, note FROM assumptions",
            ):
                try:
                    expected = (
                        json.loads(row[4]) if row[4] is not None
                        else None
                    )
                    observed = (
                        json.loads(row[9]) if row[9] is not None
                        else None
                    )
                except (json.JSONDecodeError, ValueError):
                    expected, observed = None, None
                self._entries[row[0]] = Assumption(
                    id=row[0],
                    statement=row[1],
                    related_decision_id=row[2],
                    kpi=row[3],
                    expected_value=expected,
                    tolerance=float(row[5]),
                    status=row[6],
                    created_ts=float(row[7]),
                    resolved_ts=(
                        float(row[8]) if row[8] is not None else None
                    ),
                    observed_value=observed,
                    note=row[10] or "",
                )

    def _persist(self, a: Assumption) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO assumptions("
            "  id, statement, related_decision_id, kpi, "
            "  expected_value, tolerance, status, "
            "  created_ts, resolved_ts, observed_value, note"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                a.id, a.statement, a.related_decision_id, a.kpi,
                (
                    json.dumps(a.expected_value)
                    if a.expected_value is not None else None
                ),
                a.tolerance, a.status, a.created_ts, a.resolved_ts,
                (
                    json.dumps(a.observed_value)
                    if a.observed_value is not None else None
                ),
                a.note,
            ),
        )
        self._conn.commit()

    # ── Intake ───────────────────────────────────────────

    def assume(
        self,
        *,
        statement: str,
        related_decision_id: str = "",
        kpi: str = "",
        expected_value: float | None = None,
        tolerance: float = 0.0,
    ) -> Assumption:
        if not statement:
            raise ValueError("statement required")
        if tolerance < 0:
            raise ValueError("tolerance must be ≥ 0")
        a = Assumption(
            id=uuid.uuid4().hex,
            statement=statement,
            related_decision_id=str(related_decision_id or ""),
            kpi=str(kpi or ""),
            expected_value=(
                float(expected_value)
                if expected_value is not None else None
            ),
            tolerance=float(tolerance),
            status="pending",
            created_ts=time.time(),
        )
        with self._lock:
            self._entries[a.id] = a
            self._persist(a)
        return a

    # ── Validate ─────────────────────────────────────────

    def validate(
        self,
        assumption_id: str,
        observed_value: float,
        *,
        note: str = "",
    ) -> Assumption:
        with self._lock:
            a = self._entries.get(assumption_id)
            if a is None:
                raise ValueError(
                    f"unknown assumption {assumption_id!r}",
                )
            if a.status != "pending":
                raise ValueError(
                    f"assumption already {a.status}; cannot validate",
                )
            observed = float(observed_value)
            a.observed_value = observed
            a.resolved_ts = time.time()
            if a.expected_value is None:
                a.status = "validated"
            else:
                diff = abs(observed - a.expected_value)
                if diff <= a.tolerance:
                    a.status = "validated"
                else:
                    a.status = "violated"
            if note:
                a.note = note
            self._persist(a)
            return a

    def abandon(
        self, assumption_id: str, *, note: str = "",
    ) -> Assumption:
        with self._lock:
            a = self._entries.get(assumption_id)
            if a is None:
                raise ValueError(
                    f"unknown assumption {assumption_id!r}",
                )
            if a.status != "pending":
                raise ValueError(
                    f"assumption already {a.status}; cannot abandon",
                )
            a.status = "abandoned"
            a.resolved_ts = time.time()
            if note:
                a.note = note
            self._persist(a)
            return a

    # ── Queries ──────────────────────────────────────────

    def get(self, assumption_id: str) -> Assumption | None:
        with self._lock:
            return self._entries.get(assumption_id)

    def by_status(self, status: Status) -> list[Assumption]:
        with self._lock:
            out = [
                a for a in self._entries.values()
                if a.status == status
            ]
        out.sort(key=lambda a: -a.created_ts)
        return out

    def by_decision(
        self, decision_id: str,
    ) -> list[Assumption]:
        with self._lock:
            out = [
                a for a in self._entries.values()
                if a.related_decision_id == decision_id
            ]
        out.sort(key=lambda a: a.created_ts)
        return out

    def violation_rate(self) -> float:
        with self._lock:
            resolved = [
                a for a in self._entries.values()
                if a.status in ("validated", "violated")
            ]
            if not resolved:
                return 0.0
            violated = sum(
                1 for a in resolved if a.status == "violated"
            )
            return violated / len(resolved)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for a in self._entries.values():
                counts[a.status] = counts.get(a.status, 0) + 1
            return {
                "total": len(self._entries),
                "by_status": counts,
                "violation_rate": round(
                    self.violation_rate(), 4,
                ),
            }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
