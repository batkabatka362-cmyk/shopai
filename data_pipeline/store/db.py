"""ShopAIDatabase — SQLite-backed persistent storage for all Shopify store data.

Stores: products, orders, customers, analytics snapshots, sync history.
Each store gets its own tables (prefixed by store_id).
Thread-safe via connection-per-thread pattern.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("data_pipeline.db")


def _safe_json_loads(text: Any, default: Any) -> Any:
    """Parse JSON from a DB column, returning *default* on any error.

    Pre-audit ``_product_to_dict`` / ``_order_to_dict`` /
    ``_customer_to_dict`` called ``json.loads(d.get("tags", "[]"))``
    directly — a corrupted JSON column (from a crash mid-write
    or a manual DB edit) propagated the JSONDecodeError out of
    the data accessor, taking down whatever engine was using
    the result. Audit pass 48.
    """
    if text is None:
        return default
    if not isinstance(text, (str, bytes, bytearray)):
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("db: failed to decode JSON column, using default")
        return default


def _safe_json_dumps(value: Any, default: str = "{}") -> str:
    """Serialize *value* to JSON, returning *default* on any error.

    Pre-audit ``save_snapshot`` / ``upsert_*`` used bare
    ``json.dumps(value)`` — a non-serialisable value (set,
    datetime, custom object) crashed the write. Audit pass 48.
    """
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("db: failed to encode JSON value (%s), using default", exc)
        return default

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "shopai.db"


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: Original ShopAIDatabase schema (stores, products, orders, customers,
    analytics_snapshots, sync_log)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stores (
            store_id    TEXT PRIMARY KEY,
            shop_url    TEXT NOT NULL,
            name        TEXT DEFAULT '',
            niche       TEXT DEFAULT '',
            store_type  TEXT DEFAULT 'dropshipping',
            status      TEXT DEFAULT 'active',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            config      TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS products (
            id              TEXT NOT NULL,
            store_id        TEXT NOT NULL,
            shopify_id      TEXT DEFAULT '',
            title           TEXT NOT NULL,
            price           REAL DEFAULT 0,
            cost            REAL DEFAULT 0,
            compare_at_price REAL DEFAULT 0,
            vendor          TEXT DEFAULT '',
            product_type    TEXT DEFAULT '',
            tags            TEXT DEFAULT '[]',
            status          TEXT DEFAULT 'active',
            inventory_qty   INTEGER DEFAULT 0,
            weight          REAL DEFAULT 0,
            image_url       TEXT DEFAULT '',
            description     TEXT DEFAULT '',
            variants        TEXT DEFAULT '[]',
            raw_data        TEXT DEFAULT '{}',
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL,
            synced_at       REAL DEFAULT 0,
            PRIMARY KEY (id, store_id),
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id              TEXT NOT NULL,
            store_id        TEXT NOT NULL,
            shopify_id      TEXT DEFAULT '',
            total           REAL DEFAULT 0,
            subtotal        REAL DEFAULT 0,
            financial_status TEXT DEFAULT '',
            fulfillment_status TEXT DEFAULT '',
            item_count      INTEGER DEFAULT 0,
            customer_id     TEXT DEFAULT '',
            line_items      TEXT DEFAULT '[]',
            raw_data        TEXT DEFAULT '{}',
            order_date      REAL DEFAULT 0,
            created_at      REAL NOT NULL,
            synced_at       REAL DEFAULT 0,
            PRIMARY KEY (id, store_id),
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS customers (
            id              TEXT NOT NULL,
            store_id        TEXT NOT NULL,
            shopify_id      TEXT DEFAULT '',
            name            TEXT DEFAULT '',
            email           TEXT DEFAULT '',
            orders_count    INTEGER DEFAULT 0,
            total_spent     REAL DEFAULT 0,
            tags            TEXT DEFAULT '[]',
            raw_data        TEXT DEFAULT '{}',
            first_order_at  REAL DEFAULT 0,
            last_order_at   REAL DEFAULT 0,
            created_at      REAL NOT NULL,
            synced_at       REAL DEFAULT 0,
            PRIMARY KEY (id, store_id),
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id    TEXT NOT NULL,
            snapshot_type TEXT NOT NULL,
            data        TEXT NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id    TEXT NOT NULL,
            sync_type   TEXT NOT NULL,
            status      TEXT NOT NULL,
            records     INTEGER DEFAULT 0,
            duration_s  REAL DEFAULT 0,
            error       TEXT DEFAULT '',
            created_at  REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE INDEX IF NOT EXISTS idx_products_store ON products(store_id);
        CREATE INDEX IF NOT EXISTS idx_orders_store ON orders(store_id);
        CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(store_id, order_date);
        CREATE INDEX IF NOT EXISTS idx_customers_store ON customers(store_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_store ON analytics_snapshots(store_id, snapshot_type);
        CREATE INDEX IF NOT EXISTS idx_sync_log_store ON sync_log(store_id, created_at);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class ShopAIDatabase:
    """SQLite database for persistent Shopify data storage."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB_PATH)
        self._local = threading.local()
        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Connection ───────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Schema ───────────────────────────────────────────────

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._get_conn(), "shopai", _MIGRATIONS).run()
        register_schema("shopai", Path(self._db_path), _SCHEMA_VERSION)
        logger.info("Database initialized at %s", self._db_path)

    # ── Stores ───────────────────────────────────────────────

    def add_store(self, store_id: str, shop_url: str, **kwargs: Any) -> dict[str, Any]:
        now = time.time()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO stores
               (store_id, shop_url, name, niche, store_type, status, created_at, updated_at, config)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                store_id, shop_url,
                kwargs.get("name", ""),
                kwargs.get("niche", ""),
                kwargs.get("store_type", "dropshipping"),
                "active", now, now,
                json.dumps(kwargs.get("config", {})),
            ),
        )
        conn.commit()
        return {"store_id": store_id, "shop_url": shop_url, "status": "added"}

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM stores WHERE store_id = ?", (store_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_stores(self, status: str = "active") -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM stores WHERE status = ? ORDER BY created_at", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Products ─────────────────────────────────────────────

    def upsert_products(self, store_id: str, products: list[dict[str, Any]]) -> int:
        # Defensive coercion of public entry point. Audit pass 48.
        if not isinstance(store_id, str) or not store_id:
            return 0
        if not isinstance(products, list):
            return 0
        now = time.time()
        conn = self._get_conn()
        count = 0
        try:
            for p in products:
                if not isinstance(p, dict):
                    continue
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO products
                           (id, store_id, shopify_id, title, price, cost, compare_at_price,
                            vendor, product_type, tags, status, inventory_qty, weight,
                            image_url, description, variants, raw_data, created_at, updated_at, synced_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(p.get("id") or ""), store_id,
                            str(p.get("shopify_id") or p.get("id") or ""),
                            str(p.get("title") or p.get("name") or ""),
                            safe_float(p.get("price")),
                            safe_float(p.get("cost")),
                            safe_float(p.get("compare_at_price")),
                            str(p.get("vendor") or ""),
                            str(p.get("product_type") or p.get("category") or ""),
                            _safe_json_dumps(p.get("tags") or [], default="[]"),
                            str(p.get("status") or "active"),
                            safe_int(p.get("inventory_quantity") or p.get("inventory_qty")),
                            safe_float(p.get("weight")),
                            str(p.get("image_url") or ""),
                            str(p.get("body_html") or p.get("description") or ""),
                            _safe_json_dumps(p.get("variants") or [], default="[]"),
                            _safe_json_dumps(p.get("_raw") or {}),
                            safe_float(p.get("created_at_ts"), default=now),
                            now, now,
                        ),
                    )
                    count += 1
                except sqlite3.Error as exc:
                    logger.warning("db: upsert_products skipped row (%s): %s", p.get("id"), exc)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        return count

    def get_products(self, store_id: str, status: str = "active", limit: int = 500) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM products WHERE store_id = ? AND status = ? ORDER BY updated_at DESC LIMIT ?",
            (store_id, status, limit),
        ).fetchall()
        return [self._product_to_dict(r) for r in rows]

    def get_product(self, store_id: str, product_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM products WHERE store_id = ? AND id = ?",
            (store_id, product_id),
        ).fetchone()
        return self._product_to_dict(row) if row else None

    # ── Orders ───────────────────────────────────────────────

    def upsert_orders(self, store_id: str, orders: list[dict[str, Any]]) -> int:
        if not isinstance(store_id, str) or not store_id:
            return 0
        if not isinstance(orders, list):
            return 0
        now = time.time()
        conn = self._get_conn()
        count = 0
        try:
            for o in orders:
                if not isinstance(o, dict):
                    continue
                line_items = o.get("line_items") or []
                if not isinstance(line_items, list):
                    line_items = []
                # ``item_count`` fallback cascade: explicit field
                # → ``items`` alias → length of line_items.
                item_count_raw = o.get("item_count")
                if item_count_raw is None:
                    item_count_raw = o.get("items")
                if item_count_raw is None:
                    item_count_raw = len(line_items)
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO orders
                           (id, store_id, shopify_id, total, subtotal, financial_status,
                            fulfillment_status, item_count, customer_id, line_items,
                            raw_data, order_date, created_at, synced_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(o.get("id") or ""), store_id,
                            str(o.get("shopify_id") or o.get("id") or ""),
                            safe_float(o.get("total") or o.get("total_price")),
                            safe_float(o.get("subtotal") or o.get("subtotal_price")),
                            str(o.get("financial_status") or o.get("status") or ""),
                            str(o.get("fulfillment_status") or ""),
                            safe_int(item_count_raw),
                            str(o.get("customer_id") or ""),
                            _safe_json_dumps(line_items, default="[]"),
                            _safe_json_dumps(o.get("_raw") or {}),
                            safe_float(o.get("order_date_ts"), default=now),
                            now, now,
                        ),
                    )
                    count += 1
                except sqlite3.Error as exc:
                    logger.warning("db: upsert_orders skipped row (%s): %s", o.get("id"), exc)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        return count

    def get_orders(self, store_id: str, days_back: int = 30, limit: int = 1000) -> list[dict[str, Any]]:
        cutoff = time.time() - (days_back * 86400)
        rows = self._get_conn().execute(
            "SELECT * FROM orders WHERE store_id = ? AND order_date >= ? ORDER BY order_date DESC LIMIT ?",
            (store_id, cutoff, limit),
        ).fetchall()
        return [self._order_to_dict(r) for r in rows]

    def get_all_orders(self, store_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM orders WHERE store_id = ? ORDER BY order_date DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
        return [self._order_to_dict(r) for r in rows]

    # ── Customers ────────────────────────────────────────────

    def upsert_customers(self, store_id: str, customers: list[dict[str, Any]]) -> int:
        if not isinstance(store_id, str) or not store_id:
            return 0
        if not isinstance(customers, list):
            return 0
        now = time.time()
        conn = self._get_conn()
        count = 0
        try:
            for c in customers:
                if not isinstance(c, dict):
                    continue
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO customers
                           (id, store_id, shopify_id, name, email, orders_count,
                            total_spent, tags, raw_data, created_at, synced_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(c.get("id") or ""), store_id,
                            str(c.get("shopify_id") or c.get("id") or ""),
                            str(c.get("name") or ""),
                            str(c.get("email") or ""),
                            safe_int(c.get("orders_count") or c.get("orders")),
                            safe_float(c.get("total_spent")),
                            _safe_json_dumps(c.get("tags") or [], default="[]"),
                            _safe_json_dumps(c.get("_raw") or {}),
                            now, now,
                        ),
                    )
                    count += 1
                except sqlite3.Error as exc:
                    logger.warning("db: upsert_customers skipped row (%s): %s", c.get("id"), exc)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        return count

    def get_customers(self, store_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM customers WHERE store_id = ? ORDER BY total_spent DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
        return [self._customer_to_dict(r) for r in rows]

    # ── Analytics Snapshots ──────────────────────────────────

    def save_snapshot(self, store_id: str, snapshot_type: str, data: dict[str, Any]) -> int:
        conn = self._get_conn()
        # ``_safe_json_dumps`` catches non-serialisable values
        # (sets, datetimes, custom objects) — pre-audit a
        # single bad snapshot took down the snapshot pipeline
        # entirely. Audit pass 48.
        cursor = conn.execute(
            "INSERT INTO analytics_snapshots (store_id, snapshot_type, data, created_at) VALUES (?, ?, ?, ?)",
            (store_id, snapshot_type, _safe_json_dumps(data, default="{}"), time.time()),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_snapshots(self, store_id: str, snapshot_type: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            """SELECT * FROM analytics_snapshots
               WHERE store_id = ? AND snapshot_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (store_id, snapshot_type, limit),
        ).fetchall()
        # ``_safe_json_loads`` survives a corrupted ``data``
        # column from an old crash mid-write.
        return [{"id": r["id"], "type": r["snapshot_type"],
                 "data": _safe_json_loads(r["data"], default={}),
                 "created_at": r["created_at"]}
                for r in rows]

    # ── Sync Log ─────────────────────────────────────────────

    def log_sync(self, store_id: str, sync_type: str, status: str,
                 records: int = 0, duration_s: float = 0, error: str = "") -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sync_log (store_id, sync_type, status, records, duration_s, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (store_id, sync_type, status, records, duration_s, error, time.time()),
        )
        conn.commit()

    def get_sync_history(self, store_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM sync_log WHERE store_id = ? ORDER BY created_at DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_sync(self, store_id: str, sync_type: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM sync_log WHERE store_id = ? AND sync_type = ? ORDER BY created_at DESC LIMIT 1",
            (store_id, sync_type),
        ).fetchone()
        return dict(row) if row else None

    # ── Stats ────────────────────────────────────────────────

    def get_store_stats(self, store_id: str) -> dict[str, Any]:
        conn = self._get_conn()
        products = conn.execute("SELECT COUNT(*) as c FROM products WHERE store_id = ?", (store_id,)).fetchone()
        orders = conn.execute("SELECT COUNT(*) as c FROM orders WHERE store_id = ?", (store_id,)).fetchone()
        customers = conn.execute("SELECT COUNT(*) as c FROM customers WHERE store_id = ?", (store_id,)).fetchone()
        revenue = conn.execute("SELECT COALESCE(SUM(total), 0) as s FROM orders WHERE store_id = ?", (store_id,)).fetchone()
        return {
            "store_id": store_id,
            "products": products["c"] if products else 0,
            "orders": orders["c"] if orders else 0,
            "customers": customers["c"] if customers else 0,
            "total_revenue": round(revenue["s"], 2) if revenue else 0,
        }

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _product_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Pre-audit ``json.loads(d.get("tags", "[]"))`` propagated
        # JSONDecodeError from a corrupted column. Audit pass 48.
        d["tags"] = _safe_json_loads(d.get("tags"), default=[])
        d["variants"] = _safe_json_loads(d.get("variants"), default=[])
        d["name"] = d.pop("title", "")
        d["category"] = d.pop("product_type", "")
        d["inventory_quantity"] = d.pop("inventory_qty", 0)
        return d

    @staticmethod
    def _order_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["line_items"] = _safe_json_loads(d.get("line_items"), default=[])
        d["items"] = d.pop("item_count", 0)
        d["status"] = d.pop("financial_status", "")
        return d

    @staticmethod
    def _customer_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["tags"] = _safe_json_loads(d.get("tags"), default=[])
        d["orders"] = d.pop("orders_count", 0)
        return d
