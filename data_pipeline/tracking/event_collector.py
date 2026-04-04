"""EventCollector — tracks all store events for AI learning.

Collects: orders, price changes, product additions, marketing actions,
customer interactions, and their outcomes.

This data feeds ML models. More data = smarter AI.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("event_collector")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "events.db"


class EventCollector:
    """Collects and stores all store events for ML training."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        self._buffer: list[dict] = []
        self._buffer_lock = threading.Lock()
        self._flush_size = 50
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_schema(self) -> None:
        self._get_conn().executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id    TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                entity_type TEXT DEFAULT '',
                entity_id   TEXT DEFAULT '',
                data        TEXT DEFAULT '{}',
                outcome     TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id    TEXT NOT NULL,
                product_id  TEXT NOT NULL,
                old_price   REAL DEFAULT 0,
                new_price   REAL DEFAULT 0,
                reason      TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS training_data (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                model_type  TEXT NOT NULL,
                features    TEXT NOT NULL,
                label       TEXT NOT NULL,
                weight      REAL DEFAULT 1.0,
                created_at  REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_price_product ON price_history(store_id, product_id);
            CREATE INDEX IF NOT EXISTS idx_training_model ON training_data(model_type);
        """)
        self._get_conn().commit()

    # ── Record Events ──────���─────────────────────────────────

    def track(self, store_id: str, event_type: str, entity_type: str = "",
              entity_id: str = "", data: dict | None = None) -> None:
        """Track any event."""
        event = {
            "store_id": store_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "data": json.dumps(data or {}),
            "timestamp": time.time(),
        }
        with self._buffer_lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._flush_size:
                self._flush()

    def track_order(self, store_id: str, order: dict) -> None:
        self.track(store_id, "order_created", "order",
                  str(order.get("id", "")), {
                      "total": order.get("total", 0),
                      "items": order.get("items", 0),
                      "customer_id": order.get("customer_id", ""),
                  })

    def track_price_change(self, store_id: str, product_id: str,
                          old_price: float, new_price: float, reason: str = "") -> None:
        self.track(store_id, "price_changed", "product", product_id, {
            "old_price": old_price, "new_price": new_price, "reason": reason,
        })
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO price_history (store_id, product_id, old_price, new_price, reason, timestamp) VALUES (?,?,?,?,?,?)",
            (store_id, product_id, old_price, new_price, reason, time.time()),
        )
        conn.commit()

    def track_product_added(self, store_id: str, product: dict) -> None:
        self.track(store_id, "product_added", "product",
                  str(product.get("id", "")), {
                      "name": product.get("name", product.get("title", "")),
                      "price": product.get("price", 0),
                      "category": product.get("category", ""),
                  })

    def track_ai_decision(self, store_id: str, decision_type: str,
                         decision: dict, outcome: dict | None = None) -> None:
        self.track(store_id, "ai_decision", "decision", decision_type, {
            "decision": decision, "outcome": outcome,
        })

    # ── Training Data Generation ─────────────────────────────

    def add_training_sample(self, model_type: str, features: dict,
                           label: Any, weight: float = 1.0) -> None:
        """Store a training sample for ML models."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO training_data (model_type, features, label, weight, created_at) VALUES (?,?,?,?,?)",
            (model_type, json.dumps(features), json.dumps(label), weight, time.time()),
        )
        conn.commit()

    def get_training_data(self, model_type: str, limit: int = 10000) -> list[dict[str, Any]]:
        """Get training data for a specific model."""
        rows = self._get_conn().execute(
            "SELECT features, label, weight FROM training_data WHERE model_type = ? ORDER BY created_at DESC LIMIT ?",
            (model_type, limit),
        ).fetchall()
        return [{
            "features": json.loads(r["features"]),
            "label": json.loads(r["label"]),
            "weight": r["weight"],
        } for r in rows]

    def generate_pricing_training_data(self, store_id: str) -> int:
        """Generate training data from price change history + outcomes."""
        conn = self._get_conn()
        price_changes = conn.execute(
            "SELECT * FROM price_history WHERE store_id = ? ORDER BY timestamp",
            (store_id,),
        ).fetchall()

        count = 0
        for pc in price_changes:
            # Find orders after price change for this product
            orders_after = conn.execute(
                """SELECT COUNT(*) as c FROM events
                   WHERE store_id = ? AND event_type = 'order_created'
                   AND timestamp > ? AND timestamp < ?""",
                (store_id, pc["timestamp"], pc["timestamp"] + 604800),  # 7 days
            ).fetchone()

            self.add_training_sample("pricing", {
                "product_id": pc["product_id"],
                "old_price": pc["old_price"],
                "new_price": pc["new_price"],
                "price_change_pct": (pc["new_price"] - pc["old_price"]) / pc["old_price"] if pc["old_price"] > 0 else 0,
            }, {
                "orders_7d": orders_after["c"] if orders_after else 0,
                "success": (orders_after["c"] if orders_after else 0) > 0,
            })
            count += 1

        return count

    # ── Query Events ─────────────────────────────────────────

    def get_events(self, store_id: str, event_type: str = "",
                   limit: int = 100) -> list[dict[str, Any]]:
        if event_type:
            rows = self._get_conn().execute(
                "SELECT * FROM events WHERE store_id = ? AND event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (store_id, event_type, limit),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM events WHERE store_id = ? ORDER BY timestamp DESC LIMIT ?",
                (store_id, limit),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d.get("data", "{}"))
            results.append(d)
        return results

    def get_price_history(self, store_id: str, product_id: str = "",
                         limit: int = 100) -> list[dict[str, Any]]:
        if product_id:
            rows = self._get_conn().execute(
                "SELECT * FROM price_history WHERE store_id = ? AND product_id = ? ORDER BY timestamp DESC LIMIT ?",
                (store_id, product_id, limit),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM price_history WHERE store_id = ? ORDER BY timestamp DESC LIMIT ?",
                (store_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, store_id: str = "") -> dict[str, Any]:
        conn = self._get_conn()
        if store_id:
            total = conn.execute("SELECT COUNT(*) as c FROM events WHERE store_id = ?", (store_id,)).fetchone()
            types = conn.execute(
                "SELECT event_type, COUNT(*) as c FROM events WHERE store_id = ? GROUP BY event_type",
                (store_id,),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()
            types = conn.execute("SELECT event_type, COUNT(*) as c FROM events GROUP BY event_type").fetchall()

        training = conn.execute("SELECT model_type, COUNT(*) as c FROM training_data GROUP BY model_type").fetchall()

        return {
            "total_events": total["c"] if total else 0,
            "by_type": {r["event_type"]: r["c"] for r in types},
            "training_data": {r["model_type"]: r["c"] for r in training},
        }

    # ── Flush ────────────────────────────────────────────────

    def _flush(self) -> None:
        if not self._buffer:
            return
        conn = self._get_conn()
        for e in self._buffer:
            conn.execute(
                "INSERT INTO events (store_id, event_type, entity_type, entity_id, data, timestamp) VALUES (?,?,?,?,?,?)",
                (e["store_id"], e["event_type"], e["entity_type"], e["entity_id"], e["data"], e["timestamp"]),
            )
        conn.commit()
        self._buffer.clear()

    def flush(self) -> None:
        with self._buffer_lock:
            self._flush()

    def close(self) -> None:
        self.flush()
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Singleton
_collector: EventCollector | None = None


def get_event_collector() -> EventCollector:
    global _collector
    if _collector is None:
        _collector = EventCollector()
    return _collector
