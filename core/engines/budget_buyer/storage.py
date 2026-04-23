"""SQLite-backed LTV storage.

One row per customer. Thread-safe via a coarse lock — write
rate is bounded by Shopify's order webhook cadence (dozens
per minute at most in a typical dropshipping cohort).

Schema stable — no in-place column edits, new fields always
append-only. Re-opening is always safe.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import Any

from core.engines.budget_buyer.ltv import CustomerLTV

_logger = logging.getLogger("shopai.budget_buyer.storage")


_DEFAULT_DB_PATH = "data/ltv.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_ltv (
    customer_id       TEXT PRIMARY KEY,
    email             TEXT NOT NULL,
    orders_count      INTEGER NOT NULL,
    total_spent_usd   REAL NOT NULL,
    first_order_at    REAL NOT NULL,
    last_order_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ltv_total
    ON customer_ltv(total_spent_usd DESC);
CREATE INDEX IF NOT EXISTS idx_ltv_orders
    ON customer_ltv(orders_count DESC);
CREATE INDEX IF NOT EXISTS idx_ltv_last
    ON customer_ltv(last_order_at DESC);
"""


_VALID_SORT_COLUMNS = {
    "total_spent_usd",
    "orders_count",
    "last_order_at",
    "first_order_at",
}


class LTVStorage:
    """CRUD wrapper around the ``customer_ltv`` table."""

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
    ) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript(_SCHEMA)

    def upsert(self, ltv: CustomerLTV) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO customer_ltv "
                "(customer_id, email, orders_count, "
                "total_spent_usd, first_order_at, "
                "last_order_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(customer_id) DO UPDATE SET "
                "email = excluded.email, "
                "orders_count = excluded.orders_count, "
                "total_spent_usd = excluded.total_spent_usd, "
                "first_order_at = MIN("
                "    customer_ltv.first_order_at,"
                "    excluded.first_order_at"
                "), "
                "last_order_at = MAX("
                "    customer_ltv.last_order_at,"
                "    excluded.last_order_at"
                ")",
                (
                    ltv.customer_id, ltv.email,
                    ltv.orders_count, ltv.total_spent_usd,
                    ltv.first_order_at, ltv.last_order_at,
                ),
            )
            c.commit()

    def get(self, customer_id: str) -> CustomerLTV | None:
        if not customer_id:
            return None
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM customer_ltv "
                "WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
        return self._row(row) if row else None

    def top(
        self,
        *,
        limit: int = 20,
        by: str = "total_spent_usd",
    ) -> list[CustomerLTV]:
        if by not in _VALID_SORT_COLUMNS:
            raise ValueError(
                f"invalid sort column {by!r}. "
                f"Allowed: {sorted(_VALID_SORT_COLUMNS)}",
            )
        limit = max(1, min(int(limit), 10_000))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM customer_ltv "
                f"ORDER BY {by} DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def all(self) -> list[CustomerLTV]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM customer_ltv"
            ).fetchall()
        return [self._row(r) for r in rows]

    def total_count(self) -> int:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM customer_ltv"
            ).fetchone()
        return int(row["n"] or 0)

    @staticmethod
    def _row(r: sqlite3.Row) -> CustomerLTV:
        return CustomerLTV(
            customer_id=r["customer_id"],
            email=r["email"],
            orders_count=int(r["orders_count"] or 0),
            total_spent_usd=float(r["total_spent_usd"] or 0),
            first_order_at=float(r["first_order_at"] or 0),
            last_order_at=float(r["last_order_at"] or 0),
        )
