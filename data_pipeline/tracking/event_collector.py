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

from utils.helpers import safe_float
from utils.logger import get_logger

logger = get_logger("event_collector")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "events.db"


def _safe_json_dumps(value: Any, default: str = "{}") -> str:
    """Serialize to JSON, returning *default* on any error.

    Mirrors the helper added to ``data_pipeline.store.db`` in
    pass 48. The event collector writes arbitrary caller-
    supplied dicts into ``events.data`` and ``training_data.
    features`` / ``label`` — bare ``json.dumps(value)``
    crashed on sets, datetimes, and custom objects.
    """
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("event_collector: failed to encode JSON (%s)", exc)
        return default


def _safe_json_loads(text: Any, default: Any) -> Any:
    """Parse JSON, returning *default* on any error."""
    if text is None:
        return default
    if not isinstance(text, (str, bytes, bytearray)):
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("event_collector: failed to decode JSON column")
        return default


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: events + price_history + training_data."""
    conn.executescript("""
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


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


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
        from core.db.migrations import Migrator, register_schema
        Migrator(self._get_conn(), "events", _MIGRATIONS).run()
        register_schema("events", Path(self._db_path), _SCHEMA_VERSION)

    # ── Record Events ──────���─────────────────────────────────

    def track(self, store_id: str, event_type: str, entity_type: str = "",
              entity_id: str = "", data: dict | None = None) -> None:
        """Track any event."""
        # Defensive coercion of public entry point. Audit pass 49.
        store_id = store_id if isinstance(store_id, str) else ""
        event_type = event_type if isinstance(event_type, str) else ""
        entity_type = entity_type if isinstance(entity_type, str) else ""
        entity_id = entity_id if isinstance(entity_id, str) else ""
        if not event_type:
            return
        event = {
            "store_id": store_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "data": _safe_json_dumps(data or {}),
            "timestamp": time.time(),
        }
        with self._buffer_lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._flush_size:
                self._flush()

    def track_order(self, store_id: str, order: dict) -> None:
        if not isinstance(order, dict):
            return
        self.track(store_id, "order_created", "order",
                  str(order.get("id") or ""), {
                      "total": order.get("total", 0),
                      "items": order.get("items", 0),
                      "customer_id": order.get("customer_id", ""),
                  })

    def track_price_change(self, store_id: str, product_id: str,
                          old_price: float, new_price: float, reason: str = "") -> None:
        # Coerce numerics so non-numeric strings don't crash
        # the REAL-column INSERT below. Audit pass 49.
        old_price = safe_float(old_price)
        new_price = safe_float(new_price)
        self.track(store_id, "price_changed", "product", product_id, {
            "old_price": old_price, "new_price": new_price, "reason": reason,
        })
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO price_history (store_id, product_id, old_price, new_price, reason, timestamp) VALUES (?,?,?,?,?,?)",
                (store_id, product_id, old_price, new_price, reason, time.time()),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("event_collector: price_history insert failed: %s", exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

    def track_product_added(self, store_id: str, product: dict) -> None:
        if not isinstance(product, dict):
            return
        self.track(store_id, "product_added", "product",
                  str(product.get("id") or ""), {
                      "name": product.get("name") or product.get("title") or "",
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
        if not isinstance(model_type, str) or not model_type:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO training_data (model_type, features, label, weight, created_at) VALUES (?,?,?,?,?)",
                (
                    model_type,
                    _safe_json_dumps(features),
                    _safe_json_dumps(label),
                    safe_float(weight, default=1.0),
                    time.time(),
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("event_collector: add_training_sample failed: %s", exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

    def get_training_data(self, model_type: str, limit: int = 10000) -> list[dict[str, Any]]:
        """Get training data for a specific model."""
        rows = self._get_conn().execute(
            "SELECT features, label, weight FROM training_data WHERE model_type = ? ORDER BY created_at DESC LIMIT ?",
            (model_type, limit),
        ).fetchall()
        # ``json.loads`` replaced with ``_safe_json_loads`` —
        # a corrupted row no longer takes down the whole
        # training batch. Audit pass 49.
        return [{
            "features": _safe_json_loads(r["features"], default={}),
            "label": _safe_json_loads(r["label"], default=None),
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
            d["data"] = _safe_json_loads(d.get("data"), default={})
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
        """Write buffered events to the DB.

        Audit pass 49 bug fix: pre-audit the inner
        ``conn.execute(...)`` could raise mid-iteration on a
        single bad event. The exception propagated out of the
        for loop, ``conn.commit()`` and ``self._buffer.clear()``
        never ran, the partial transaction stayed open, and
        every subsequent ``track()`` call appended MORE events
        to the already-full buffer. Buffer grew unbounded
        until memory exhaustion — a real resource leak.

        Fix:
          * Per-event try/except so one bad event is dropped
            with a warning instead of killing the whole batch.
          * Buffer is cleared and commit is attempted even on
            partial success.
          * Rollback on transaction-level failure.
        """
        if not self._buffer:
            return
        conn = self._get_conn()
        to_flush = list(self._buffer)
        # Clear FIRST so we never retry the same failing batch
        # on the next ``track()`` call — drop-on-failure is
        # the right policy for a fire-and-forget event
        # collector.
        self._buffer.clear()

        good = 0
        for e in to_flush:
            try:
                conn.execute(
                    "INSERT INTO events (store_id, event_type, entity_type, entity_id, data, timestamp) VALUES (?,?,?,?,?,?)",
                    (
                        e.get("store_id", ""),
                        e.get("event_type", ""),
                        e.get("entity_type", ""),
                        e.get("entity_id", ""),
                        e.get("data", "{}"),
                        e.get("timestamp", time.time()),
                    ),
                )
                good += 1
            except sqlite3.Error as exc:
                logger.warning("event_collector: skipped bad event: %s", exc)
        try:
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("event_collector: commit failed: %s", exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        if good:
            logger.debug("event_collector: flushed %d/%d events", good, len(to_flush))

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
_collector_lock = threading.Lock()


def get_event_collector() -> EventCollector:
    """Thread-safe singleton accessor.

    Pre-audit two concurrent first-callers could both pass
    the ``None`` check and both construct an EventCollector —
    the second overwrote the first, discarding the first
    collector's buffered events and its DB connection.
    Audit pass 49.
    """
    global _collector
    with _collector_lock:
        if _collector is None:
            _collector = EventCollector()
        return _collector
