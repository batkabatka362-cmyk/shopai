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
            # Try GraphQL first (includes costs!)
            products = self._fetch_products_graphql(creds)
            if products is None:
                # Fallback to REST
                from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
                api = ShopifyAPI(creds["shop_url"], creds["api_key"])
                raw = api.fetch_products(creds["shop_url"], creds["api_key"])
                products = self._normalize_products(raw.get("products", []))

            if products:
                count = self._sm.db.upsert_products(store_id, products)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "products", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2)}

        except Exception as exc:
            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "products", "error", 0, elapsed, str(exc))
            logger.error("Product sync failed for %s: %s", store_id, exc)
            return {"count": 0, "error": str(exc)}

    def _sync_orders(self, store_id: str, creds: dict[str, str], days_back: int = 30) -> dict[str, Any]:
        start = time.monotonic()
        try:
            # Try GraphQL first
            orders = self._fetch_orders_graphql(creds)
            if orders is None:
                from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
                api = ShopifyAPI(creds["shop_url"], creds["api_key"])
                raw = api.fetch_orders(creds["shop_url"], creds["api_key"], days_back=days_back)
                orders = self._normalize_orders(raw.get("orders", []))

            if orders:
                count = self._sm.db.upsert_orders(store_id, orders)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "orders", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2)}

        except Exception as exc:
            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "orders", "error", 0, elapsed, str(exc))
            logger.error("Order sync failed for %s: %s", store_id, exc)
            return {"count": 0, "error": str(exc)}

    def _sync_customers(self, store_id: str, creds: dict[str, str]) -> dict[str, Any]:
        start = time.monotonic()
        try:
            # Try GraphQL first
            customers = self._fetch_customers_graphql(creds)
            if customers is None:
                from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
                api = ShopifyAPI(creds["shop_url"], creds["api_key"])
                raw = api.fetch_customers(creds["shop_url"], creds["api_key"])
                customers = self._normalize_customers(raw.get("customers", []))

            if customers:
                count = self._sm.db.upsert_customers(store_id, customers)
            else:
                count = 0

            elapsed = time.monotonic() - start
            self._sm.db.log_sync(store_id, "customers", "success", count, elapsed)
            return {"count": count, "duration_s": round(elapsed, 2)}

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

    def _fetch_products_graphql(self, creds: dict[str, str]) -> list[dict] | None:
        """Fetch products via GraphQL (includes costs in one query)."""
        try:
            from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
            gql = ShopifyGraphQL(creds["shop_url"], creds["api_key"])
            products = gql.get_all_products()
            if products:
                # GraphQL normalizer already includes cost from inventoryItem.unitCost
                return [{
                    "id": p.get("id", ""),
                    "shopify_id": p.get("id", ""),
                    "title": p.get("name", ""),
                    "price": p.get("price", 0),
                    "cost": p.get("cost", 0),
                    "compare_at_price": p.get("compare_at_price", 0),
                    "vendor": p.get("vendor", ""),
                    "product_type": p.get("category", ""),
                    "tags": p.get("tags", []),
                    "status": p.get("status", "active"),
                    "inventory_quantity": p.get("inventory_quantity", 0),
                    "image_url": p.get("image_url", ""),
                    "body_html": p.get("description", ""),
                    "variants": p.get("variants", []),
                } for p in products]
        except Exception as exc:
            logger.debug("GraphQL products fetch failed, using REST: %s", exc)
        return None

    def _fetch_orders_graphql(self, creds: dict[str, str]) -> list[dict] | None:
        """Fetch orders via GraphQL."""
        try:
            from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
            gql = ShopifyGraphQL(creds["shop_url"], creds["api_key"])
            result = gql.get_orders(first=50)
            orders = result.get("orders", [])
            if orders is not None:
                return [{
                    "id": o.get("id", ""),
                    "shopify_id": o.get("id", ""),
                    "total": o.get("total", 0),
                    "subtotal": o.get("subtotal", 0),
                    "financial_status": o.get("status", ""),
                    "fulfillment_status": o.get("fulfillment_status", ""),
                    "item_count": o.get("items", 0),
                    "customer_id": o.get("customer_id", ""),
                    "line_items": o.get("line_items", []),
                } for o in orders]
        except Exception as exc:
            logger.debug("GraphQL orders fetch failed, using REST: %s", exc)
        return None

    def _fetch_customers_graphql(self, creds: dict[str, str]) -> list[dict] | None:
        """Fetch customers via GraphQL."""
        try:
            from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
            gql = ShopifyGraphQL(creds["shop_url"], creds["api_key"])
            result = gql.get_customers(first=50)
            customers = result.get("customers", [])
            if customers is not None:
                return [{
                    "id": c.get("id", ""),
                    "shopify_id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "email": c.get("email", ""),
                    "orders_count": c.get("orders", 0),
                    "total_spent": c.get("total_spent", 0),
                    "tags": c.get("tags", []),
                } for c in customers]
        except Exception as exc:
            logger.debug("GraphQL customers fetch failed, using REST: %s", exc)
        return None

    def _sync_product_costs(self, store_id: str, creds: dict[str, str], products: list[dict]) -> None:
        """Fetch product costs via inventory_items API (costs not in products endpoint)."""
        try:
            import json, urllib.request
            token = creds["api_key"]
            shop = creds["shop_url"]
            conn = self._sm.db._get_conn()

            for p in products:
                variant = p.get("variants", [{}])[0] if p.get("variants") else {}
                inv_item_id = variant.get("inventory_item_id")
                if not inv_item_id:
                    continue
                try:
                    url = f"https://{shop}/admin/api/2024-01/inventory_items/{inv_item_id}.json"
                    req = urllib.request.Request(url, headers={"X-Shopify-Access-Token": token})
                    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
                    cost = float(data.get("inventory_item", {}).get("cost", 0) or 0)
                    if cost > 0:
                        conn.execute(
                            "UPDATE products SET cost = ? WHERE store_id = ? AND shopify_id = ?",
                            (cost, store_id, str(p["id"])),
                        )
                except Exception:
                    pass

            conn.commit()
        except Exception as exc:
            logger.debug("Cost sync: %s", exc)

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
