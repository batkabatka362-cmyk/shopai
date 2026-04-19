"""Budget ledger — rolling day/week/month accounting with reservations.

feasibility_gate rejects a single over-budget action. That's not
enough when many small actions each fit individually but their *sum*
blows the budget. The ledger tracks accumulated spend per category
per time window, supports atomic *reserve → commit* (or *release*)
semantics, and exposes clean *remaining* queries.

Each category has three windows by default — day, week, month —
each with its own cap. An action that exceeds the smallest-window
remaining amount is rejected.

Reserve / commit / release:

  reserve(category, amount)        → reservation_id
  commit(reservation_id, actual)   — finalises the spend
  release(reservation_id)          — drops the reservation (no spend)

Reservations are intentionally durable: if the cycle crashes between
reserve and commit, the reserved amount stays held (protecting the
cap) until ``housekeep()`` reaps reservations older than a TTL.

SQLite-persisted. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS budget_caps (
    category  TEXT NOT NULL,
    window    TEXT NOT NULL,
    cap_usd   REAL NOT NULL,
    PRIMARY KEY (category, window)
);
CREATE TABLE IF NOT EXISTS spend_entries (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    amount_usd   REAL NOT NULL,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    reservation  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    note         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_se_cat_ts
    ON spend_entries(category, ts);
CREATE INDEX IF NOT EXISTS idx_se_active
    ON spend_entries(active, ts);
"""


_WINDOW_SECONDS: dict[str, float] = {
    "day":   86_400.0,
    "week":  7 * 86_400.0,
    "month": 30 * 86_400.0,
}


@dataclass
class Reservation:
    id: str
    category: str
    amount: float
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "amount": round(self.amount, 4),
            "ts": self.ts,
        }


@dataclass
class BudgetStatus:
    category: str
    window: str
    cap_usd: float
    spent_usd: float
    reserved_usd: float
    remaining_usd: float
    utilisation: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "window": self.window,
            "cap_usd": round(self.cap_usd, 4),
            "spent_usd": round(self.spent_usd, 4),
            "reserved_usd": round(self.reserved_usd, 4),
            "remaining_usd": round(self.remaining_usd, 4),
            "utilisation": round(self.utilisation, 4),
        }


class BudgetExceeded(Exception):
    pass


class BudgetLedger:
    def __init__(
        self,
        db_path: str | Path = "data/budget_ledger.db",
        *,
        reservation_ttl_s: float = 6 * 3600.0,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._reservation_ttl_s = float(reservation_ttl_s)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Caps ──────────────────────────────────────────────

    def set_cap(
        self, category: str, window: str, cap_usd: float,
    ) -> None:
        if not category:
            raise ValueError("category required")
        if window not in _WINDOW_SECONDS:
            raise ValueError(
                f"window must be one of {sorted(_WINDOW_SECONDS)}",
            )
        if cap_usd < 0:
            raise ValueError("cap_usd must be non-negative")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO budget_caps"
                "(category, window, cap_usd) VALUES (?,?,?)",
                (category, window, float(cap_usd)),
            )
            self._conn.commit()

    def cap(self, category: str, window: str) -> float | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT cap_usd FROM budget_caps "
                "WHERE category=? AND window=?",
                (category, window),
            ).fetchone()
        return float(row[0]) if row else None

    # ── Reserve / commit / release ───────────────────────

    def _spent_in_window(
        self,
        category: str,
        window_s: float,
        include_reservations: bool,
    ) -> float:
        cutoff = time.time() - window_s
        if include_reservations:
            q = (
                "SELECT COALESCE(SUM(amount_usd), 0) FROM spend_entries "
                "WHERE category=? AND active=1 AND ts >= ?"
            )
        else:
            q = (
                "SELECT COALESCE(SUM(amount_usd), 0) FROM spend_entries "
                "WHERE category=? AND active=1 AND reservation=0 AND ts >= ?"
            )
        with self._lock:
            row = self._conn.execute(
                q, (category, cutoff),
            ).fetchone()
        return float(row[0] or 0.0)

    def _fits(
        self, category: str, amount: float,
    ) -> tuple[bool, str]:
        """Check amount against ALL windows with caps. Returns
        (fits, reason). The strictest window wins."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT window, cap_usd FROM budget_caps WHERE category=?",
                (category,),
            ).fetchall()
        for window, cap in rows:
            sec = _WINDOW_SECONDS[window]
            spent = self._spent_in_window(
                category, sec, include_reservations=True,
            )
            if spent + amount > float(cap):
                return False, (
                    f"{category} {window} cap ${cap:.2f} exceeded: "
                    f"{spent:.2f} + {amount:.2f}"
                )
        return True, ""

    def reserve(
        self, category: str, amount_usd: float,
    ) -> Reservation:
        if not category:
            raise ValueError("category required")
        if amount_usd <= 0:
            raise ValueError("amount_usd must be positive")
        amount = float(amount_usd)
        fits, reason = self._fits(category, amount)
        if not fits:
            raise BudgetExceeded(reason)
        rid = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO spend_entries"
                "(id, category, amount_usd, ts, kind, "
                " reservation, active, note) "
                "VALUES (?, ?, ?, ?, 'reserve', 1, 1, '')",
                (rid, category, amount, now),
            )
            self._conn.commit()
        return Reservation(
            id=rid, category=category, amount=amount, ts=now,
        )

    def commit(
        self,
        reservation_id: str,
        actual_amount: float | None = None,
        note: str = "",
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT category, amount_usd FROM spend_entries "
                "WHERE id=? AND reservation=1 AND active=1",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown or inactive reservation {reservation_id!r}",
                )
            category, reserved = row
            amount = (
                float(actual_amount)
                if actual_amount is not None else float(reserved)
            )
            # Retire reservation, record actual spend as a fresh entry.
            self._conn.execute(
                "UPDATE spend_entries SET active=0 WHERE id=?",
                (reservation_id,),
            )
            self._conn.execute(
                "INSERT INTO spend_entries"
                "(id, category, amount_usd, ts, kind, "
                " reservation, active, note) "
                "VALUES (?, ?, ?, ?, 'commit', 0, 1, ?)",
                (uuid.uuid4().hex, category, amount,
                 time.time(), note),
            )
            self._conn.commit()

    def release(self, reservation_id: str) -> None:
        with self._lock:
            n = self._conn.execute(
                "UPDATE spend_entries SET active=0 "
                "WHERE id=? AND reservation=1 AND active=1",
                (reservation_id,),
            ).rowcount
            self._conn.commit()
        if n == 0:
            raise ValueError(
                f"unknown or inactive reservation {reservation_id!r}",
            )

    # ── Direct record (no reservation) ────────────────────

    def spend(
        self,
        category: str,
        amount_usd: float,
        *,
        note: str = "",
    ) -> None:
        """One-shot spend with a built-in fit check."""
        if amount_usd <= 0:
            raise ValueError("amount_usd must be positive")
        fits, reason = self._fits(category, float(amount_usd))
        if not fits:
            raise BudgetExceeded(reason)
        with self._lock:
            self._conn.execute(
                "INSERT INTO spend_entries"
                "(id, category, amount_usd, ts, kind, "
                " reservation, active, note) "
                "VALUES (?, ?, ?, ?, 'spend', 0, 1, ?)",
                (uuid.uuid4().hex, category, float(amount_usd),
                 time.time(), note),
            )
            self._conn.commit()

    # ── Status + housekeeping ────────────────────────────

    def status(
        self, category: str, window: str,
    ) -> BudgetStatus:
        cap = self.cap(category, window)
        sec = _WINDOW_SECONDS[window]
        spent = self._spent_in_window(
            category, sec, include_reservations=False,
        )
        reserved = (
            self._spent_in_window(
                category, sec, include_reservations=True,
            )
            - spent
        )
        cap_val = float(cap) if cap is not None else 0.0
        remaining = max(0.0, cap_val - spent - reserved)
        utilisation = (
            (spent + reserved) / cap_val if cap_val > 0 else 0.0
        )
        return BudgetStatus(
            category=category, window=window,
            cap_usd=cap_val, spent_usd=spent,
            reserved_usd=reserved, remaining_usd=remaining,
            utilisation=utilisation,
        )

    def overview(self) -> list[BudgetStatus]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category, window FROM budget_caps "
                "ORDER BY category, window",
            ).fetchall()
        return [self.status(c, w) for c, w in rows]

    def housekeep(self, now: float | None = None) -> int:
        """Reap stale reservations. Returns number released."""
        now = now or time.time()
        cutoff = now - self._reservation_ttl_s
        with self._lock:
            n = self._conn.execute(
                "UPDATE spend_entries SET active=0 "
                "WHERE reservation=1 AND active=1 AND ts < ?",
                (cutoff,),
            ).rowcount
            self._conn.commit()
        return int(n)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM spend_entries WHERE active=1",
            ).fetchone()[0])
            reservations = int(self._conn.execute(
                "SELECT COUNT(*) FROM spend_entries "
                "WHERE active=1 AND reservation=1",
            ).fetchone()[0])
            caps = int(self._conn.execute(
                "SELECT COUNT(*) FROM budget_caps",
            ).fetchone()[0])
        return {
            "active_entries": total,
            "active_reservations": reservations,
            "caps_registered": caps,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
