"""SyncService — fetches data from Shopify API and stores in local DB.

Supports: full sync, incremental sync, scheduled sync.
Works with multiple stores via StoreManager.
"""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("sync_service")


class SyncService:
    """Syncs Shopify store data to local SQLite database."""

    def __init__(self, store_manager: Any = None) -> None:
        from data_pipeline.store.store_manager import StoreManager
        self._sm: StoreManager = store_manager or StoreManager()
        self._running = False
        self._sync_thread: threading.Thread | None = None
        self._sync_interval = 300  # 5 minutes default

    # ── Full Sync ────────────────────────────────────────────

    def sync_store(self, store_id: str = "") -> dict[str, Any]:
        """Full sync: fetch all data from Shopify and store in DB."""
        sid = store_id or self._sm.active_store_id
        if not sid:
            return {"status": "error", "error": "No store specified"}

        creds = self._sm.get_credentials(sid)
        if not creds.get("shop_url") or not creds.get("api_key"):
            return {"status": "error", "error": "Missing credentials for store"}

        logger.info("Starting full sync for store: %s", sid)
        start = time.monotonic()
        results: dict[str, Any] = {"store_id": sid, "synced": {}}

        # Sync products
        product_result = self._sync_products(sid, creds)
        results["synced"]["products"] = product_result

        # Sync orders
        order_result = self._sync_orders(sid, creds)
        results["synced"]["orders"] = order_result

        # Sync customers
        customer_result = self._sync_customers(sid, creds)
        results["synced"]["customers"] = customer_result

        elapsed = time.monotonic() - start
        results["duration_s"] = round(elapsed, 2)
        results["status"] = "success"

        # Save analytics snapshot
        self._save_sync_snapshot(sid, results)

        logger.info("Full sync completed for %s in %.1fs", sid, elapsed)
        return results

    def sync_all_stores(self) -> list[dict[str, Any]]:
        """Sync all active stores."""
        stores = self._sm.list_stores()
        results = []
        for store in stores:
            result = self.sync_store(store["store_id"])
            results.append(result)
        return results

    # ── Incremental Sync ─────────────────────────────────────

    def sync_recent_orders(self, store_id: str = "", days_back: int = 1) -> dict[str, Any]:
        """Quick sync: only fetch recent orders (for frequent updates)."""
        sid = store_id or self._sm.active_store_id
        creds = self._sm.get_credentials(sid)
        if not creds.get("shop_url"):
            return {"status": "error", "error": "Missing credentials"}

        return self._sync_orders(sid, creds, days_back=days_back)

    # ── Scheduled Sync ───────────────────────────────────────

    def start_auto_sync(self, interval_seconds: int = 300) -> dict[str, Any]:
        """Start background auto-sync thread."""
        if self._running:
            return {"status": "already_running", "interval": self._sync_interval}

        self._sync_interval = interval_seconds
        self._running = True
        self._sync_thread = threading.Thread(
            target=self._auto_sync_loop, daemon=True, name="shopai-sync"
        )
        self._sync_thread.start()
        logger.info("Auto-sync started (every %ds)", interval_seconds)
        return {"status": "started", "interval": interval_seconds}

    def stop_auto_sync(self) -> dict[str, Any]:
        """Stop background auto-sync."""
        self._running = False
        logger.info("Auto-sync stopped")
        return {"status": "stopped"}

    def _auto_sync_loop(self) -> None:
        """Background sync loop."""
        while self._running:
            try:
                self.sync_all_stores()
            except Exception as exc:
                logger.error("Auto-sync error: %s", exc)
            # Sleep in small increments so stop is responsive
            for _ in range(self._sync_interval):
                if not self._running:
                    break
                time.sleep(1)

    # ── Internal sync methods ────────────────────────────────

    def _sync_products(self, store_id: str, creds: dict[str, str]) -> dict[str, Any]:
        start = time.monotonic()
        try:
            from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
            api = ShopifyAPI(creds["shop_url"], creds["api_key"])
            raw = api.fetch_products(creds["shop_url"], creds["api_key"])

            products = raw.get("products", [])
            if products:
                # Normalize for DB storage
                normalized = self._normalize_products(products)
                count = self._sm.db.upsert_products(store_id, normalized)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "products", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2), "errors": raw.get("errors", [])}

        except Exception as exc:
            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "products", "error", 0, elapsed, str(exc))
            logger.error("Product sync failed for %s: %s", store_id, exc)
            return {"count": 0, "error": str(exc)}

    def _sync_orders(self, store_id: str, creds: dict[str, str], days_back: int = 30) -> dict[str, Any]:
        start = time.monotonic()
        try:
            from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
            api = ShopifyAPI(creds["shop_url"], creds["api_key"])
            raw = api.fetch_orders(creds["shop_url"], creds["api_key"], days_back=days_back)

            orders = raw.get("orders", [])
            if orders:
                normalized = self._normalize_orders(orders)
                count = self._sm.db.upsert_orders(store_id, normalized)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "orders", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2), "errors": raw.get("errors", [])}

        except Exception as exc:
            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "orders", "error", 0, elapsed, str(exc))
            logger.error("Order sync failed for %s: %s", store_id, exc)
            return {"count": 0, "error": str(exc)}

    def _sync_customers(self, store_id: str, creds: dict[str, str]) -> dict[str, Any]:
        start = time.monotonic()
        try:
            from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
            api = ShopifyAPI(creds["shop_url"], creds["api_key"])
            raw = api.fetch_customers(creds["shop_url"], creds["api_key"])

            customers = raw.get("customers", [])
            if customers:
                normalized = self._normalize_customers(customers)
                count = self._sm.db.upsert_customers(store_id, normalized)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "customers", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2), "errors": raw.get("errors", [])}

        except Exception as exc:
            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "customers", "error", 0, elapsed, str(exc))
            logger.error("Customer sync failed for %s: %s", store_id, exc)
            return {"count": 0, "error": str(exc)}

    def _save_sync_snapshot(self, store_id: str, results: dict[str, Any]) -> None:
        """Save a snapshot of store stats after sync."""
        stats = self._sm.db.get_store_stats(store_id)
        stats["sync_results"] = results.get("synced", {})
        self._sm.db.save_snapshot(store_id, "post_sync", stats)

    # ── Normalizers (Shopify API → DB format) ────────────────

    @staticmethod
    def _normalize_products(raw_products: list[dict]) -> list[dict[str, Any]]:
        """Convert raw Shopify API products to DB-ready format."""
        normalized = []
        for p in raw_products:
            variant = p.get("variants", [{}])[0] if p.get("variants") else {}
            normalized.append({
                "id": str(p.get("id", "")),
                "shopify_id": str(p.get("id", "")),
                "title": p.get("title", ""),
                "price": float(variant.get("price", 0) or 0),
                "cost": float(variant.get("cost", 0) or 0),
                "compare_at_price": float(variant.get("compare_at_price", 0) or 0),
                "vendor": p.get("vendor", ""),
                "product_type": p.get("product_type", ""),
                "tags": p.get("tags", "").split(", ") if isinstance(p.get("tags"), str) else p.get("tags", []),
                "status": p.get("status", "active"),
                "inventory_quantity": int(variant.get("inventory_quantity", 0) or 0),
                "weight": float(variant.get("weight", 0) or 0),
                "image_url": (p.get("image", {}) or {}).get("src", ""),
                "body_html": p.get("body_html", ""),
                "variants": p.get("variants", []),
                "_raw": p,
            })
        return normalized

    @staticmethod
    def _normalize_orders(raw_orders: list[dict]) -> list[dict[str, Any]]:
        normalized = []
        for o in raw_orders:
            normalized.append({
                "id": str(o.get("id", "")),
                "shopify_id": str(o.get("id", "")),
                "total": float(o.get("total_price", 0) or 0),
                "subtotal": float(o.get("subtotal_price", 0) or 0),
                "financial_status": o.get("financial_status", ""),
                "fulfillment_status": o.get("fulfillment_status", ""),
                "item_count": len(o.get("line_items", [])),
                "customer_id": str((o.get("customer") or {}).get("id", "")),
                "line_items": o.get("line_items", []),
                "_raw": o,
            })
        return normalized

    @staticmethod
    def _normalize_customers(raw_customers: list[dict]) -> list[dict[str, Any]]:
        normalized = []
        for c in raw_customers:
            normalized.append({
                "id": str(c.get("id", "")),
                "shopify_id": str(c.get("id", "")),
                "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                "email": c.get("email", ""),
                "orders_count": int(c.get("orders_count", 0) or 0),
                "total_spent": float(c.get("total_spent", 0) or 0),
                "tags": c.get("tags", "").split(", ") if isinstance(c.get("tags"), str) else c.get("tags", []),
                "_raw": c,
            })
        return normalized

    # ── Status ───────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        stores = self._sm.list_stores()
        sync_info = []
        for s in stores:
            last = self._sm.db.get_last_sync(s["store_id"], "products")
            sync_info.append({
                "store_id": s["store_id"],
                "last_sync": last["created_at"] if last else None,
                "last_status": last["status"] if last else "never",
            })
        return {
            "auto_sync_running": self._running,
            "interval_s": self._sync_interval,
            "stores": sync_info,
        }
