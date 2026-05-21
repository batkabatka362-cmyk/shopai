"""Shopify commerce adapter for ShopAI — connected to real Shopify API.

Uses ShopifyAPI client for reads and ProductUpdater for writes.
Falls back to DB cache when live API is unavailable.
"""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)
from utils.logger import get_logger

logger = get_logger("tools.shopify")


class ShopifyAdapter(BaseToolAdapter):
    tool_name = "shopify"
    tool_category = "commerce"
    version = "2.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._shop_domain: str = ""
        self._api_version: str = "2024-01"
        self._api = None
        self._updater = None

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._shop_domain = credentials.get("shop_domain", "")
        self._api_version = credentials.get("api_version", self._api_version)
        # Initialize real API client
        if self._shop_domain and credentials.get("access_token"):
            try:
                from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
                self._api = ShopifyAPI(self._shop_domain, credentials["access_token"])
                logger.info("ShopifyAdapter connected to %s", self._shop_domain)
            except Exception as exc:
                logger.warning("Failed to init ShopifyAPI: %s", exc)
            try:
                from execution.shopify.product_updater import ProductUpdater
                self._updater = ProductUpdater()
            except Exception as exc:
                logger.warning("Failed to init ProductUpdater: %s", exc)

    def capabilities(self) -> list[str]:
        return [
            "fetch_products",
            "fetch_orders",
            "fetch_customers",
            "create_product",
            "update_product",
            "update_price",
            "update_inventory",
            "get_store_info",
            "manage_collections",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "fetch_products": self._fetch_products,
            "fetch_orders": self._fetch_orders,
            "fetch_customers": self._fetch_customers,
            "create_product": self._create_product,
            "update_product": self._update_product,
            "update_price": self._update_price,
            "update_inventory": self._update_inventory,
            "get_store_info": self._get_store_info,
            "manage_collections": self._manage_collections,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(
                success=False, data={}, error=f"Unknown action: {action}"
            )
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._credentials.get("access_token"))
        # Capture the actual probe exception so the HealthStatus
        # surface tells operators WHY (auth failure / network /
        # schema) instead of the generic "unreachable" message.
        probe_error: str | None = None
        if healthy and self._api:
            try:
                self._api.fetch_products(self._shop_domain, self._credentials["access_token"])
            except Exception as exc:  # noqa: BLE001
                healthy = False
                probe_error = str(exc)
                logger.warning(
                    "ShopifyAdapter health probe failed (shop=%s): %s",
                    self._shop_domain, exc,
                )
        latency = (time.monotonic() - start) * 1000
        if healthy:
            error_msg = None
        elif probe_error:
            error_msg = f"Shopify API probe failed: {probe_error}"
        else:
            error_msg = "Shopify API unreachable or not configured"
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=error_msg,
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=2.0, burst=40, daily_quota=None)

    # ── READ handlers (real API → DB cache → empty) ──────────

    def _fetch_products(self, params: dict) -> dict:
        """Fetch products from Shopify API, with DB cache fallback."""
        if self._api:
            try:
                raw = self._api.fetch_products(self._shop_domain, self._credentials.get("access_token", ""))
                products = raw.get("products", [])
                # Store in DB cache
                self._cache_to_db("products", products)
                return {"products": products, "total": len(products), "source": "live_api"}
            except Exception as exc:
                logger.warning("Live fetch_products failed, trying cache: %s", exc)

        # Fallback to DB cache
        cached = self._read_from_db("products", params.get("limit", 50))
        if cached:
            return {"products": cached, "total": len(cached), "source": "db_cache"}

        return {"products": [], "total": 0, "source": "none"}

    def _fetch_orders(self, params: dict) -> dict:
        if self._api:
            try:
                days_back = params.get("days_back", 30)
                raw = self._api.fetch_orders(
                    self._shop_domain, self._credentials.get("access_token", ""),
                    days_back=days_back,
                )
                orders = raw.get("orders", [])
                self._cache_to_db("orders", orders)
                return {"orders": orders, "total": len(orders), "source": "live_api"}
            except Exception as exc:
                logger.warning("Live fetch_orders failed, trying cache: %s", exc)

        cached = self._read_from_db("orders", params.get("limit", 100))
        if cached:
            return {"orders": cached, "total": len(cached), "source": "db_cache"}

        return {"orders": [], "total": 0, "source": "none"}

    def _fetch_customers(self, params: dict) -> dict:
        if self._api:
            try:
                raw = self._api.fetch_customers(self._shop_domain, self._credentials.get("access_token", ""))
                customers = raw.get("customers", [])
                self._cache_to_db("customers", customers)
                return {"customers": customers, "total": len(customers), "source": "live_api"}
            except Exception as exc:
                logger.warning("Live fetch_customers failed, trying cache: %s", exc)

        cached = self._read_from_db("customers", params.get("limit", 100))
        if cached:
            return {"customers": cached, "total": len(cached), "source": "db_cache"}

        return {"customers": [], "total": 0, "source": "none"}

    # ── WRITE handlers (real API calls) ──────────────────────

    def _create_product(self, params: dict) -> dict:
        if "title" not in params:
            raise ValueError("title is required to create a product")
        if not self._updater:
            raise RuntimeError("ProductUpdater not configured — set credentials first")

        payload = {
            "product": {
                "title": params["title"],
                "body_html": params.get("body_html", ""),
                "vendor": params.get("vendor", ""),
                "product_type": params.get("product_type", ""),
                "tags": params.get("tags", []),
            }
        }
        # Use urllib-based updater for the actual API call
        from execution.shopify.product_updater import ProductUpdater
        updater = ProductUpdater()
        url = f"https://{self._shop_domain}/admin/api/{self._api_version}/products.json"
        result = updater._make_request(
            "POST", url,
            updater._build_headers(self._credentials.get("access_token", "")),
            payload,
        )
        return {"product": result.get("product", result), "status": "created"}

    def _update_product(self, params: dict) -> dict:
        if "product_id" not in params:
            raise ValueError("product_id is required")
        if not self._updater:
            raise RuntimeError("ProductUpdater not configured")

        pid = params["product_id"]
        updates = {k: v for k, v in params.items() if k != "product_id"}
        result = self._updater.update_product(
            self._shop_domain, self._credentials.get("access_token", ""),
            pid, updates,
        )
        return result

    def _update_price(self, params: dict) -> dict:
        if "variant_id" not in params or "price" not in params:
            raise ValueError("variant_id and price are required")
        if not self._updater:
            raise RuntimeError("ProductUpdater not configured")

        result = self._updater.update_price(
            self._shop_domain, self._credentials.get("access_token", ""),
            params.get("product_id", ""),
            params["variant_id"],
            params["price"],
        )
        return result

    def _update_inventory(self, params: dict) -> dict:
        if "inventory_item_id" not in params or "available" not in params:
            raise ValueError("inventory_item_id and available are required")
        if not self._updater:
            raise RuntimeError("ProductUpdater not configured")

        result = self._updater.update_inventory(
            self._shop_domain, self._credentials.get("access_token", ""),
            params["inventory_item_id"],
            params.get("location_id", ""),
            params["available"],
        )
        return result

    def _get_store_info(self, params: dict) -> dict:
        """Get store info — try live API, fallback to stored config.

        Mirrors the _fetch_* handlers' fall-back-with-log pattern
        (line 146-147 etc.) so operators see the signal when the
        live API call silently degrades to the config-only path.
        """
        if self._api:
            try:
                from execution.shopify.product_updater import ProductUpdater
                updater = ProductUpdater()
                url = f"https://{self._shop_domain}/admin/api/{self._api_version}/shop.json"
                result = updater._make_request(
                    "GET", url,
                    updater._build_headers(self._credentials.get("access_token", "")),
                )
                return {"shop": result.get("shop", result), "source": "live_api"}
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Live get_store_info failed (shop=%s), "
                    "falling back to config: %s",
                    self._shop_domain, exc,
                )
        return {"shop_domain": self._shop_domain, "source": "config"}

    def _manage_collections(self, params: dict) -> dict:
        sub = params.get("sub_action", "list")
        if not self._api:
            return {"collections": [], "source": "not_connected"}

        from execution.shopify.product_updater import ProductUpdater
        updater = ProductUpdater()
        token = self._credentials.get("access_token", "")

        if sub == "list":
            url = f"https://{self._shop_domain}/admin/api/{self._api_version}/custom_collections.json"
            result = updater._make_request("GET", url, updater._build_headers(token))
            return {"collections": result.get("custom_collections", []), "source": "live_api"}

        if sub == "create":
            if "title" not in params:
                raise ValueError("title is required to create a collection")
            url = f"https://{self._shop_domain}/admin/api/{self._api_version}/custom_collections.json"
            payload = {"custom_collection": {"title": params["title"]}}
            result = updater._make_request("POST", url, updater._build_headers(token), payload)
            return {"collection": result.get("custom_collection", result), "status": "created"}

        raise ValueError(f"Unknown sub_action: {sub}")

    # ── DB cache helpers ─────────────────────────────────────

    def _cache_to_db(self, data_type: str, records: list) -> None:
        """Cache fetched data to SQLite for offline access."""
        try:
            from data_pipeline.store.db import ShopAIDatabase
            db = ShopAIDatabase()
            store_id = self._shop_domain.replace(".myshopify.com", "")
            if data_type == "products":
                db.upsert_products(store_id, records)
            elif data_type == "orders":
                db.upsert_orders(store_id, records)
            elif data_type == "customers":
                db.upsert_customers(store_id, records)
        except Exception as exc:
            logger.debug("DB cache write failed (non-critical): %s", exc)

    def _read_from_db(self, data_type: str, limit: int = 100) -> list:
        """Read cached data from SQLite."""
        try:
            from data_pipeline.store.db import ShopAIDatabase
            db = ShopAIDatabase()
            store_id = self._shop_domain.replace(".myshopify.com", "")
            if data_type == "products":
                return db.get_products(store_id, limit=limit)
            elif data_type == "orders":
                return db.get_orders(store_id, limit=limit)
            elif data_type == "customers":
                return db.get_customers(store_id, limit=limit)
        except Exception as exc:
            logger.debug("DB cache read failed (non-critical): %s", exc)
        return []
