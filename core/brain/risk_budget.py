"""Risk budget — portfolio-level risk caps per category.

budget_ledger (v25-D6) tracks dollars. risk_budget tracks the *risk
units* a portfolio can carry. Every decision consumes risk — a
$100/day ad test carries less risk than a sitewide 25% discount —
and the brain has a finite risk appetite per category. This module
formalises that:

  • set_cap(category, cap_units)           — owner-set ceiling
  • reserve(category, units, reason)        → reservation id
  • commit(reservation_id, actual_units)    — finalise risk used
  • release(reservation_id)                  — free the reservation
  • status(category)                         → BudgetStatus
  • overview()                                → list of BudgetStatus

Reservations survive process restarts via SQLite. Stale reservations
(older than ``reservation_ttl_s``) can be reaped by ``housekeep``.
Parallels budget_ledger's API by design so callers already familiar
with it feel at home.

Pure stdlib. Deterministic. Thread-safe (Lock).
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.risk_budget")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS risk_caps (
    category  TEXT PRIMARY KEY,
    cap_units REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_entries (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    units        REAL NOT NULL,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    reservation  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    reason       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_risk_cat_active
    ON risk_entries(category, active);
"""


@dataclass
class Reservation:
    id: str
    category: str
    units: float
    ts: float
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "units": round(self.units, 4),
            "ts": self.ts,
            "reason": self.reason,
        }


@dataclass
class BudgetStatus:
    category: str
    cap_units: float
    spent_units: float
    reserved_units: float
    remaining_units: float
    utilisation: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "cap_units": round(self.cap_units, 4),
            "spent_units": round(self.spent_units, 4),
            "reserved_units": round(self.reserved_units, 4),
            "remaining_units": round(self.remaining_units, 4),
            "utilisation": round(self.utilisation, 4),
        }


class RiskBudgetExceeded(Exception):
    pass


class RiskBudget:
    def __init__(
        self,
        db_path: str | Path = "data/risk_budget.db",
        *,
        reservation_ttl_s: float = 6 * 3600.0,
    ) -> None:
        if reservation_ttl_s <= 0:
            raise ValueError("reservation_ttl_s must be positive")
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        self._reservation_ttl_s = float(reservation_ttl_s)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Cap ──────────────────────────────────────────────

    def set_cap(self, category: str, cap_units: float) -> None:
        if not category:
            raise ValueError("category required")
        if cap_units < 0:
            raise ValueError("cap_units must be ≥ 0")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO risk_caps"
                "(category, cap_units) VALUES (?, ?)",
                (str(category), float(cap_units)),
            )
            self._conn.commit()

    def cap(self, category: str) -> float | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT cap_units FROM risk_caps WHERE category=?",
                (category,),
            ).fetchone()
        return float(row[0]) if row else None

    # ── Reserve / commit / release ──────────────────────

    def _active_units(
        self, category: str, *, include_reservations: bool,
    ) -> float:
        if include_reservations:
            q = (
                "SELECT COALESCE(SUM(units), 0) FROM risk_entries "
                "WHERE category=? AND active=1"
            )
        else:
            q = (
                "SELECT COALESCE(SUM(units), 0) FROM risk_entries "
                "WHERE category=? AND active=1 AND reservation=0"
            )
        with self._lock:
            row = self._conn.execute(q, (category,)).fetchone()
        return float(row[0] or 0.0)

    def _fits(
        self, category: str, units: float,
    ) -> tuple[bool, str]:
        cap = self.cap(category)
        if cap is None:
            # No cap set → unlimited (but caller should set one)
            return True, "no cap set"
        spent_and_reserved = self._active_units(
            category, include_reservations=True,
        )
        if spent_and_reserved + units > float(cap):
            return False, (
                f"{category} risk cap {cap:.4f} exceeded: "
                f"{spent_and_reserved:.4f} + {units:.4f}"
            )
        return True, ""

    def reserve(
        self, category: str, units: float, *, reason: str = "",
    ) -> Reservation:
        if not category:
            raise ValueError("category required")
        if units <= 0:
            raise ValueError("units must be positive")
        units = float(units)
        fits, msg = self._fits(category, units)
        if not fits:
            raise RiskBudgetExceeded(msg)
        rid = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO risk_entries"
                "(id, category, units, ts, kind, "
                " reservation, active, reason) "
                "VALUES (?, ?, ?, ?, 'reserve', 1, 1, ?)",
                (rid, category, units, now, reason),
            )
            self._conn.commit()
        return Reservation(
            id=rid, category=category,
            units=units, ts=now, reason=reason,
        )

    def commit(
        self,
        reservation_id: str,
        *,
        actual_units: float | None = None,
        note: str = "",
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT category, units FROM risk_entries "
                "WHERE id=? AND reservation=1 AND active=1",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown or inactive reservation {reservation_id!r}",
                )
            category, reserved = row[0], float(row[1])
            amount = (
                float(actual_units)
                if actual_units is not None else reserved
            )
            # Retire the reservation and record actual risk spend.
            self._conn.execute(
                "UPDATE risk_entries SET active=0 WHERE id=?",
                (reservation_id,),
            )
            self._conn.execute(
                "INSERT INTO risk_entries"
                "(id, category, units, ts, kind, "
                " reservation, active, reason) "
                "VALUES (?, ?, ?, ?, 'commit', 0, 1, ?)",
                (
                    uuid.uuid4().hex, category, amount,
                    time.time(), note,
                ),
            )
            self._conn.commit()

    def release(self, reservation_id: str) -> None:
        with self._lock:
            n = self._conn.execute(
                "UPDATE risk_entries SET active=0 "
                "WHERE id=? AND reservation=1 AND active=1",
                (reservation_id,),
            ).rowcount
            self._conn.commit()
        if n == 0:
            raise ValueError(
                f"unknown or inactive reservation {reservation_id!r}",
            )

    def spend(
        self, category: str, units: float,
        *, reason: str = "",
    ) -> None:
        """One-shot risk spend with built-in fit check."""
        if units <= 0:
            raise ValueError("units must be positive")
        fits, msg = self._fits(category, float(units))
        if not fits:
            raise RiskBudgetExceeded(msg)
        with self._lock:
            self._conn.execute(
                "INSERT INTO risk_entries"
                "(id, category, units, ts, kind, "
                " reservation, active, reason) "
                "VALUES (?, ?, ?, ?, 'spend', 0, 1, ?)",
                (
                    uuid.uuid4().hex, category, float(units),
                    time.time(), reason,
                ),
            )
            self._conn.commit()

    # ── Status ────────────────────────────────────────────

    def status(self, category: str) -> BudgetStatus:
        cap_value = self.cap(category) or 0.0
        spent = self._active_units(
            category, include_reservations=False,
        )
        reserved = (
            self._active_units(category, include_reservations=True)
            - spent
        )
        remaining = max(0.0, cap_value - spent - reserved)
        util = (
            (spent + reserved) / cap_value if cap_value > 0 else 0.0
        )
        return BudgetStatus(
            category=category,
            cap_units=cap_value,
            spent_units=spent,
            reserved_units=reserved,
            remaining_units=remaining,
            utilisation=util,
        )

    def overview(self) -> list[BudgetStatus]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category FROM risk_caps ORDER BY category",
            ).fetchall()
        return [self.status(r[0]) for r in rows]

    def housekeep(self, now: float | None = None) -> int:
        """Reap stale reservations. Returns the number released."""
        now = float(now if now is not None else time.time())
        cutoff = now - self._reservation_ttl_s
        with self._lock:
            n = self._conn.execute(
                "UPDATE risk_entries SET active=0 "
                "WHERE reservation=1 AND active=1 AND ts < ?",
                (cutoff,),
            ).rowcount
            self._conn.commit()
        return int(n)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM risk_entries WHERE active=1",
            ).fetchone()[0])
            reserves = int(self._conn.execute(
                "SELECT COUNT(*) FROM risk_entries "
                "WHERE active=1 AND reservation=1",
            ).fetchone()[0])
            caps = int(self._conn.execute(
                "SELECT COUNT(*) FROM risk_caps",
            ).fetchone()[0])
        return {
            "active_entries": total,
            "active_reservations": reserves,
            "caps_registered": caps,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
