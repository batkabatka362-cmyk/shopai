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

from utils.logger import get_logger

logger = get_logger("data_pipeline.db")

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
        now = time.time()
        conn = self._get_conn()
        count = 0
        for p in products:
            conn.execute(
                """INSERT OR REPLACE INTO products
                   (id, store_id, shopify_id, title, price, cost, compare_at_price,
                    vendor, product_type, tags, status, inventory_qty, weight,
                    image_url, description, variants, raw_data, created_at, updated_at, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(p.get("id", "")), store_id,
                    str(p.get("shopify_id", p.get("id", ""))),
                    p.get("title", p.get("name", "")),
                    float(p.get("price", 0) or 0),
                    float(p.get("cost", 0) or 0),
                    float(p.get("compare_at_price", 0) or 0),
                    p.get("vendor", ""),
                    p.get("product_type", p.get("category", "")),
                    json.dumps(p.get("tags", [])),
                    p.get("status", "active"),
                    int(p.get("inventory_quantity", p.get("inventory_qty", 0)) or 0),
                    float(p.get("weight", 0) or 0),
                    p.get("image_url", ""),
                    p.get("body_html", p.get("description", "")),
                    json.dumps(p.get("variants", [])),
                    json.dumps(p.get("_raw", {})),
                    p.get("created_at_ts", now),
                    now, now,
                ),
            )
            count += 1
        conn.commit()
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
        now = time.time()
        conn = self._get_conn()
        count = 0
        for o in orders:
            conn.execute(
                """INSERT OR REPLACE INTO orders
                   (id, store_id, shopify_id, total, subtotal, financial_status,
                    fulfillment_status, item_count, customer_id, line_items,
                    raw_data, order_date, created_at, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(o.get("id", "")), store_id,
                    str(o.get("shopify_id", o.get("id", ""))),
                    float(o.get("total", o.get("total_price", 0)) or 0),
                    float(o.get("subtotal", o.get("subtotal_price", 0)) or 0),
                    o.get("financial_status", o.get("status", "")),
                    o.get("fulfillment_status", ""),
                    int(o.get("item_count", o.get("items", len(o.get("line_items", [])))) or 0),
                    str(o.get("customer_id", "")),
                    json.dumps(o.get("line_items", [])),
                    json.dumps(o.get("_raw", {})),
                    o.get("order_date_ts", now),
                    now, now,
                ),
            )
            count += 1
        conn.commit()
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
        now = time.time()
        conn = self._get_conn()
        count = 0
        for c in customers:
            conn.execute(
                """INSERT OR REPLACE INTO customers
                   (id, store_id, shopify_id, name, email, orders_count,
                    total_spent, tags, raw_data, created_at, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(c.get("id", "")), store_id,
                    str(c.get("shopify_id", c.get("id", ""))),
                    c.get("name", ""),
                    c.get("email", ""),
                    int(c.get("orders_count", c.get("orders", 0)) or 0),
                    float(c.get("total_spent", 0) or 0),
                    json.dumps(c.get("tags", [])),
                    json.dumps(c.get("_raw", {})),
                    now, now,
                ),
            )
            count += 1
        conn.commit()
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
        cursor = conn.execute(
            "INSERT INTO analytics_snapshots (store_id, snapshot_type, data, created_at) VALUES (?, ?, ?, ?)",
            (store_id, snapshot_type, json.dumps(data), time.time()),
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
        return [{"id": r["id"], "type": r["snapshot_type"],
                 "data": json.loads(r["data"]), "created_at": r["created_at"]}
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
        d["tags"] = json.loads(d.get("tags", "[]"))
        d["variants"] = json.loads(d.get("variants", "[]"))
        d["name"] = d.pop("title", "")
        d["category"] = d.pop("product_type", "")
        d["inventory_quantity"] = d.pop("inventory_qty", 0)
        return d

    @staticmethod
    def _order_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["line_items"] = json.loads(d.get("line_items", "[]"))
        d["items"] = d.pop("item_count", 0)
        d["status"] = d.pop("financial_status", "")
        return d

    @staticmethod
    def _customer_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        d["orders"] = d.pop("orders_count", 0)
        return d
