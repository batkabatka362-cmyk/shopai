"""SyncService — fetches data from Shopify API and stores in local DB.

Supports: full sync, incremental sync, scheduled sync.
Works with multiple stores via StoreManager.
"""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.helpers import safe_float, safe_int
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
        """Fetch product costs via inventory_items API (costs not in products endpoint).

        Audit pass 48 fixes:
          * double-scheme URL bug (same as pass 43) — if
            ``creds["shop_url"]`` already has ``https://`` the
            pre-audit f-string produced ``https://https://shop.../``.
          * ``variants[0]`` non-list crash.
          * Bare ``float()`` on inventory cost crash.
          * ``p["id"]`` direct access on non-dict / missing key.
        """
        if not isinstance(creds, dict) or not isinstance(products, list):
            return
        try:
            import json
            import urllib.request
            from data_pipeline.ingestion.api.shopify_api import _normalize_shop_url

            token = creds.get("api_key") or ""
            shop = _normalize_shop_url(creds.get("shop_url") or "")
            if not shop or not token:
                return
            conn = self._sm.db._get_conn()

            for p in products:
                if not isinstance(p, dict):
                    continue
                variants = p.get("variants")
                variant: dict[str, Any] = {}
                if isinstance(variants, list) and variants:
                    first = variants[0]
                    if isinstance(first, dict):
                        variant = first
                inv_item_id = variant.get("inventory_item_id")
                if not inv_item_id:
                    continue
                pid = p.get("id")
                if not pid:
                    continue
                try:
                    url = f"https://{shop}/admin/api/2024-01/inventory_items/{inv_item_id}.json"
                    req = urllib.request.Request(url, headers={"X-Shopify-Access-Token": token})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read())
                    if not isinstance(data, dict):
                        continue
                    inv_item = data.get("inventory_item") or {}
                    if not isinstance(inv_item, dict):
                        continue
                    cost = safe_float(inv_item.get("cost"))
                    if cost > 0:
                        conn.execute(
                            "UPDATE products SET cost = ? WHERE store_id = ? AND shopify_id = ?",
                            (cost, store_id, str(pid)),
                        )
                except Exception as exc:  # noqa: BLE001
                    # Per-product fetch failure shouldn't abort
                    # the whole sync -- continue to next product.
                    # Debug-level so a flaky API doesn't spam,
                    # but operators chasing "why is this product's
                    # cost stale?" see the signal.
                    logger.debug(
                        "Cost sync: inventory_item fetch failed "
                        "for product %s: %s", pid, exc,
                    )

            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cost sync: %s", exc)

    @staticmethod
    def _normalize_products(raw_products: list[dict]) -> list[dict[str, Any]]:
        """Convert raw Shopify API products to DB-ready format.

        Pre-audit used bare ``float()`` / ``int()`` on variant
        fields which crashed on currency strings, and did
        ``p.get("variants", [{}])[0]`` which crashed when
        ``variants`` was a dict (not a list). Audit pass 48.
        """
        if not isinstance(raw_products, list):
            return []
        normalized = []
        for p in raw_products:
            if not isinstance(p, dict):
                continue
            # Safe variant extraction: must be a non-empty list
            # AND the first element must be a dict.
            variants_raw = p.get("variants")
            variant: dict[str, Any] = {}
            if isinstance(variants_raw, list) and variants_raw:
                first = variants_raw[0]
                if isinstance(first, dict):
                    variant = first
            # Safe image extraction.
            image = p.get("image") or {}
            if not isinstance(image, dict):
                image = {}
            # Safe tags extraction: string → split, list → as-is,
            # None / anything else → [].
            raw_tags = p.get("tags")
            if isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            elif isinstance(raw_tags, list):
                tags = raw_tags
            else:
                tags = []
            normalized.append({
                "id": str(p.get("id") or ""),
                "shopify_id": str(p.get("id") or ""),
                "title": p.get("title") or "",
                "price": safe_float(variant.get("price")),
                "cost": safe_float(variant.get("cost")),
                "compare_at_price": safe_float(variant.get("compare_at_price")),
                "vendor": p.get("vendor") or "",
                "product_type": p.get("product_type") or "",
                "tags": tags,
                "status": p.get("status") or "active",
                "inventory_quantity": safe_int(variant.get("inventory_quantity")),
                "weight": safe_float(variant.get("weight")),
                "image_url": image.get("src") or "",
                "body_html": p.get("body_html") or "",
                "variants": variants_raw if isinstance(variants_raw, list) else [],
                "_raw": p,
            })
        return normalized

    @staticmethod
    def _normalize_orders(raw_orders: list[dict]) -> list[dict[str, Any]]:
        if not isinstance(raw_orders, list):
            return []
        normalized = []
        for o in raw_orders:
            if not isinstance(o, dict):
                continue
            customer = o.get("customer") or {}
            if not isinstance(customer, dict):
                customer = {}
            line_items = o.get("line_items") or []
            if not isinstance(line_items, list):
                line_items = []
            normalized.append({
                "id": str(o.get("id") or ""),
                "shopify_id": str(o.get("id") or ""),
                "total": safe_float(o.get("total_price")),
                "subtotal": safe_float(o.get("subtotal_price")),
                "financial_status": o.get("financial_status") or "",
                "fulfillment_status": o.get("fulfillment_status") or "",
                "item_count": len(line_items),
                "customer_id": str(customer.get("id") or ""),
                "line_items": line_items,
                "_raw": o,
            })
        return normalized

    @staticmethod
    def _normalize_customers(raw_customers: list[dict]) -> list[dict[str, Any]]:
        if not isinstance(raw_customers, list):
            return []
        normalized = []
        for c in raw_customers:
            if not isinstance(c, dict):
                continue
            first = c.get("first_name") or ""
            last = c.get("last_name") or ""
            raw_tags = c.get("tags")
            if isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            elif isinstance(raw_tags, list):
                tags = raw_tags
            else:
                tags = []
            normalized.append({
                "id": str(c.get("id") or ""),
                "shopify_id": str(c.get("id") or ""),
                "name": f"{first} {last}".strip(),
                "email": c.get("email") or "",
                "orders_count": safe_int(c.get("orders_count")),
                "total_spent": safe_float(c.get("total_spent")),
                "tags": tags,
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
