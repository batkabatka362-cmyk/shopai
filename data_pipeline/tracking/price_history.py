"""Price History Tracker — records every price change for trend analysis.

Tracks:
  - Price changes per product over time
  - Competitor price changes
  - Price→revenue correlation
  - Best/worst price points per product

Used by:
  - DecisionEngine: "this product sells best at $29.99"
  - SmartExecutor: simulate pricing based on historical data
  - IntelligenceCycle: price memory for decisions
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("price_history")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "price_history.db"


class PriceHistory:
    """Tracks all price changes and their outcomes."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        self._conn().executescript("""
            CREATE TABLE IF NOT EXISTS price_points (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  TEXT NOT NULL,
                store_id    TEXT DEFAULT '',
                price       REAL NOT NULL,
                cost        REAL DEFAULT 0.0,
                margin      REAL DEFAULT 0.0,
                source      TEXT DEFAULT 'system',
                reason      TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS price_outcomes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id      TEXT NOT NULL,
                price           REAL NOT NULL,
                revenue_after   REAL DEFAULT 0.0,
                orders_after    INTEGER DEFAULT 0,
                conversion_rate REAL DEFAULT 0.0,
                period_days     INTEGER DEFAULT 7,
                score           REAL DEFAULT 3.0,
                timestamp       REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS competitor_prices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  TEXT NOT NULL,
                competitor  TEXT DEFAULT '',
                price       REAL NOT NULL,
                source      TEXT DEFAULT 'scan',
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pp_product ON price_points(product_id);
            CREATE INDEX IF NOT EXISTS idx_pp_ts ON price_points(timestamp);
            CREATE INDEX IF NOT EXISTS idx_po_product ON price_outcomes(product_id);
            CREATE INDEX IF NOT EXISTS idx_cp_product ON competitor_prices(product_id);
        """)
        self._conn().commit()

    # == RECORD PRICES =============================================

    def record_price(self, product_id: str, price: float, cost: float = 0.0,
                     source: str = "system", reason: str = "",
                     store_id: str = "") -> int:
        """Record a price point for a product."""
        margin = (price - cost) / price if price > 0 and cost > 0 else 0.0
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO price_points (product_id, store_id, price, cost, margin, source, reason, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            (str(product_id), store_id, price, cost, round(margin, 3), source, reason, time.time()),
        )
        conn.commit()
        return cur.lastrowid or 0

    def record_prices_batch(self, products: list[dict], store_id: str = "",
                            source: str = "sync") -> int:
        """Record current prices for all products (called each cycle)."""
        conn = self._conn()
        count = 0
        # Only record if price changed since last recording
        for p in products:
            pid = str(p.get("id", ""))
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            if not pid or price <= 0:
                continue

            # Check last recorded price
            last = conn.execute(
                "SELECT price FROM price_points WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (pid,),
            ).fetchone()

            if last and abs(last["price"] - price) < 0.01:
                continue  # Price unchanged, skip

            margin = (price - cost) / price if price > 0 and cost > 0 else 0.0
            conn.execute(
                "INSERT INTO price_points (product_id, store_id, price, cost, margin, source, timestamp) VALUES (?,?,?,?,?,?,?)",
                (pid, store_id, price, cost, round(margin, 3), source, time.time()),
            )
            count += 1

        conn.commit()
        return count

    def record_competitor_price(self, product_id: str, competitor: str,
                                price: float) -> None:
        """Record a competitor price observation."""
        conn = self._conn()
        conn.execute(
            "INSERT INTO competitor_prices (product_id, competitor, price, timestamp) VALUES (?,?,?,?)",
            (str(product_id), competitor, price, time.time()),
        )
        conn.commit()

    def record_outcome(self, product_id: str, price: float,
                       revenue_after: float = 0.0, orders_after: int = 0,
                       conversion_rate: float = 0.0, period_days: int = 7) -> None:
        """Record the outcome of a price point."""
        score = 3.0
        if revenue_after > 0:
            score += 0.5
        if orders_after > 0:
            score += 0.5
        if conversion_rate > 0.03:
            score += 0.5
        score = min(5.0, score)

        conn = self._conn()
        conn.execute(
            "INSERT INTO price_outcomes (product_id, price, revenue_after, orders_after, conversion_rate, period_days, score, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            (str(product_id), price, revenue_after, orders_after, conversion_rate, period_days, score, time.time()),
        )
        conn.commit()

    # == ANALYSIS ==================================================

    def get_price_history(self, product_id: str, limit: int = 50) -> list[dict]:
        """Get price history for a product."""
        rows = self._conn().execute(
            "SELECT * FROM price_points WHERE product_id = ? ORDER BY timestamp DESC LIMIT ?",
            (str(product_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_best_price(self, product_id: str) -> dict[str, Any]:
        """Find the best-performing price point for a product."""
        row = self._conn().execute(
            "SELECT * FROM price_outcomes WHERE product_id = ? ORDER BY score DESC, revenue_after DESC LIMIT 1",
            (str(product_id),),
        ).fetchone()
        return dict(row) if row else {}

    def get_price_range(self, product_id: str) -> dict[str, float]:
        """Get min/max/avg price for a product."""
        row = self._conn().execute(
            "SELECT MIN(price) as min_price, MAX(price) as max_price, AVG(price) as avg_price, COUNT(*) as points FROM price_points WHERE product_id = ?",
            (str(product_id),),
        ).fetchone()
        if row and row["points"] > 0:
            return {"min": row["min_price"], "max": row["max_price"],
                    "avg": round(row["avg_price"], 2), "points": row["points"]}
        return {"min": 0, "max": 0, "avg": 0, "points": 0}

    def get_competitor_prices(self, product_id: str) -> list[dict]:
        """Get competitor price observations for a product."""
        rows = self._conn().execute(
            "SELECT * FROM competitor_prices WHERE product_id = ? ORDER BY timestamp DESC LIMIT 20",
            (str(product_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_price_trend(self, product_id: str, days: int = 30) -> dict[str, Any]:
        """Analyze price trend over time."""
        since = time.time() - (days * 86400)
        rows = self._conn().execute(
            "SELECT price, timestamp FROM price_points WHERE product_id = ? AND timestamp >= ? ORDER BY timestamp",
            (str(product_id), since),
        ).fetchall()
        if len(rows) < 2:
            return {"trend": "insufficient_data", "points": len(rows)}

        prices = [r["price"] for r in rows]
        first_half = prices[:len(prices)//2]
        second_half = prices[len(prices)//2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_second > avg_first * 1.05:
            trend = "increasing"
        elif avg_second < avg_first * 0.95:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "points": len(rows),
            "current": prices[-1],
            "min": min(prices),
            "max": max(prices),
            "avg_first_half": round(avg_first, 2),
            "avg_second_half": round(avg_second, 2),
            "change_pct": round((avg_second - avg_first) / avg_first * 100, 1) if avg_first > 0 else 0,
        }

    # == STATS =====================================================

    def get_stats(self) -> dict[str, Any]:
        conn = self._conn()
        pp = conn.execute("SELECT COUNT(*) as c FROM price_points").fetchone()
        po = conn.execute("SELECT COUNT(*) as c FROM price_outcomes").fetchone()
        cp = conn.execute("SELECT COUNT(*) as c FROM competitor_prices").fetchone()
        products = conn.execute("SELECT COUNT(DISTINCT product_id) as c FROM price_points").fetchone()
        return {
            "price_points": pp["c"] if pp else 0,
            "outcomes": po["c"] if po else 0,
            "competitor_prices": cp["c"] if cp else 0,
            "products_tracked": products["c"] if products else 0,
        }

    def close(self) -> None:
        if hasattr(self._local, "c") and self._local.c:
            self._local.c.close()
            self._local.c = None


_instance: PriceHistory | None = None

def get_price_history() -> PriceHistory:
    global _instance
    if _instance is None:
        _instance = PriceHistory()
    return _instance
