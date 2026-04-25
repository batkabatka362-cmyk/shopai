"""ShopifyBridge — connects ShopAI engines to real Shopify store data.

Data flow:
  1. Try DB cache (fast, always available)
  2. If stale/missing → fetch from Shopify API → store in DB
  3. If both fail → raise ``ShopifyBridgeUnavailable``

Previously step 3 returned a hardcoded "mock" dataset (5 products,
5 orders, 4 customers) when both the cache and the live API
failed. Downstream engines treated the mock rows as truth and made
decisions against fictional inventory, fictional revenue, and
fictional customers — the mock silently masked real failures.

Requires: SHOPAI_SHOPIFY_URL and SHOPAI_SHOPIFY_KEY env vars.
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("bridge.shopify")


class ShopifyBridgeUnavailable(RuntimeError):
    """Raised when the bridge cannot serve a request — neither the
    DB cache nor the live Shopify API returned usable data.

    Before this class existed the bridge silently returned a small
    hardcoded mock dataset in the same situation, which let broken
    API credentials, network outages, and empty caches all masquerade
    as "successful" reads and quietly corrupt downstream decisions.
    Callers that want the old behaviour must now handle this
    exception explicitly and choose their own fallback strategy.
    """

    def __init__(self, resource: str, reason: str = "") -> None:
        msg = (
            f"ShopifyBridge cannot serve {resource!r}: no cache, "
            f"no live API data"
        )
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)
        self.resource = resource
        self.reason = reason


class ShopifyBridge:
    """Connects engines to real Shopify store data via DB cache + live API."""

    def __init__(self, shop_url: str = "", api_key: str = "") -> None:
        self._shop_url = shop_url or os.environ.get("SHOPAI_SHOPIFY_URL", "")
        self._api_key = api_key or os.environ.get("SHOPAI_SHOPIFY_KEY", "")
        self._api = None
        self._connected = False
        self._store_id = self._shop_url.replace(".myshopify.com", "").replace("https://", "")
        self._db = None

    def connect(self) -> dict[str, Any]:
        """Connect to Shopify store."""
        if not self._shop_url or not self._api_key:
            return {"connected": False, "error": "Missing SHOPAI_SHOPIFY_URL or SHOPAI_SHOPIFY_KEY"}

        try:
            from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
            self._api = ShopifyAPI(self._shop_url, self._api_key)
            self._connected = True
            logger.info("Connected to Shopify: %s", self._shop_url)

            # Initialize DB
            self._init_db()

            return {"connected": True, "shop": self._shop_url}
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    def _init_db(self) -> None:
        """Initialize DB connection for caching."""
        try:
            from data_pipeline.store.db import ShopAIDatabase
            self._db = ShopAIDatabase()
            # Ensure store exists in DB
            if self._store_id:
                self._db.add_store(self._store_id, self._shop_url)
        except Exception as exc:
            logger.debug("DB init failed (non-critical): %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- Fetch data for engines ---

    def _ensure_connected(self) -> None:
        if not self._connected and self._shop_url and self._api_key:
            self.connect()

    def fetch_products(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch products: DB cache → live API.

        Raises ``ShopifyBridgeUnavailable`` if neither path yields
        data. Pre-cleanup this method silently returned a hardcoded
        5-product mock dataset in the same failure case.
        """
        cached = self._read_cache("products", limit)
        if cached:
            return cached

        self._ensure_connected()
        last_error = ""
        if self._connected and self._api:
            try:
                raw = self._api.fetch_products(self._shop_url, self._api_key)
                products = self._normalize_products(raw.get("products", [])[:limit])
                self._write_cache("products", products)
                return products
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.error("Shopify fetch_products failed: %s", exc)

        raise ShopifyBridgeUnavailable("products", last_error)

    def fetch_orders(self, days_back: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch orders: DB cache → live API.

        Raises ``ShopifyBridgeUnavailable`` if neither path yields
        data. See ``fetch_products`` for the mock-removal rationale.
        """
        cached = self._read_cache("orders", limit)
        if cached:
            return cached

        self._ensure_connected()
        last_error = ""
        if self._connected and self._api:
            try:
                raw = self._api.fetch_orders(self._shop_url, self._api_key, days_back=days_back)
                orders = self._normalize_orders(raw.get("orders", [])[:limit])
                self._write_cache("orders", orders)
                return orders
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.error("Shopify fetch_orders failed: %s", exc)

        raise ShopifyBridgeUnavailable("orders", last_error)

    def fetch_customers(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch customers: DB cache → live API.

        Raises ``ShopifyBridgeUnavailable`` if neither path yields
        data. See ``fetch_products`` for the mock-removal rationale.
        """
        cached = self._read_cache("customers", limit)
        if cached:
            return cached

        self._ensure_connected()
        last_error = ""
        if self._connected and self._api:
            try:
                raw = self._api.fetch_customers(self._shop_url, self._api_key)
                customers = self._normalize_customers(raw.get("customers", [])[:limit])
                self._write_cache("customers", customers)
                return customers
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.error("Shopify fetch_customers failed: %s", exc)

        raise ShopifyBridgeUnavailable("customers", last_error)

    def fetch_for_engine(self, engine_name: str) -> dict[str, Any]:
        """Fetch the right data for a specific engine — uses DataProvider if available."""
        try:
            from data_pipeline.store.data_provider import DataProvider
            from data_pipeline.store.store_manager import StoreManager
            sm = StoreManager()
            if self._store_id:
                sm.add_store(self._store_id, self._shop_url, api_key=self._api_key)
            provider = DataProvider(sm)
            return provider.get_data_for_engine(engine_name, self._store_id)
        except Exception as exc:
            logger.debug("data provider fallback failed: %s", exc)

        # Fallback to direct fetch
        product_engines = {"product_selection", "pricing", "product_description", "inventory",
                           "product_ranking", "product_optimization", "catalog", "seo"}
        customer_engines = {"customer_segmentation", "churn_prediction", "retention", "loyalty",
                            "personalization", "email_marketing", "customer_analytics"}
        order_engines = {"analytics", "revenue_forecasting", "order_management", "demand_forecasting",
                         "conversion_tracking", "financial", "margin_analysis"}

        data: dict[str, Any] = {}
        if engine_name in product_engines or "product" in engine_name:
            data["products"] = self.fetch_products()
        if engine_name in customer_engines or "customer" in engine_name:
            data["customer_data"] = self.fetch_customers()
        if engine_name in order_engines or "order" in engine_name or "analytics" in engine_name:
            data["order_data"] = self.fetch_orders()

        if not data:
            data["products"] = self.fetch_products()

        return data

    # --- Push results to Shopify ---

    def push_prices(self, price_updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._connected:
            return {"pushed": False, "reason": "not_connected", "updates": len(price_updates)}

        results = []
        for update in price_updates:
            try:
                from execution.shopify.product_updater import ProductUpdater
                updater = ProductUpdater()
                result = updater.update_price(
                    self._shop_url, self._api_key,
                    update.get("product_id", ""),
                    update.get("variant_id", ""),
                    update.get("new_price", 0),
                )
                results.append({"product": update.get("name"), "status": "updated", "result": result})
            except Exception as exc:
                results.append({"product": update.get("name"), "status": "failed", "error": str(exc)})

        return {"pushed": True, "total": len(results), "results": results}

    def push_inventory(self, inventory_updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._connected:
            return {"pushed": False, "reason": "not_connected"}

        results = []
        for update in inventory_updates:
            try:
                from execution.shopify.product_updater import ProductUpdater
                updater = ProductUpdater()
                result = updater.update_inventory(
                    self._shop_url, self._api_key,
                    update.get("inventory_item_id", ""),
                    update.get("location_id", ""),
                    update.get("quantity", 0),
                )
                results.append({"item": update.get("name"), "status": "updated"})
            except Exception as exc:
                results.append({"item": update.get("name"), "status": "failed", "error": str(exc)})

        return {"pushed": True, "total": len(results), "results": results}

    # --- DB Cache ---

    def _read_cache(self, data_type: str, limit: int) -> list[dict[str, Any]]:
        """Read from SQLite cache."""
        if not self._db or not self._store_id:
            self._init_db()
        if not self._db or not self._store_id:
            return []
        try:
            if data_type == "products":
                return self._db.get_products(self._store_id, limit=limit)
            elif data_type == "orders":
                return self._db.get_orders(self._store_id, limit=limit)
            elif data_type == "customers":
                return self._db.get_customers(self._store_id, limit=limit)
        except Exception as exc:
            logger.debug("DB data retrieval failed for %s: %s", data_type, exc)
        return []

    def _write_cache(self, data_type: str, records: list[dict[str, Any]]) -> None:
        """Write to SQLite cache."""
        if not self._db or not self._store_id:
            return
        try:
            if data_type == "products":
                self._db.upsert_products(self._store_id, records)
            elif data_type == "orders":
                self._db.upsert_orders(self._store_id, records)
            elif data_type == "customers":
                self._db.upsert_customers(self._store_id, records)
        except Exception as exc:
            logger.debug("Cache write failed: %s", exc)

    # --- Normalizers ---

    @staticmethod
    def _normalize_products(raw_products: list[dict]) -> list[dict[str, Any]]:
        products = []
        for p in raw_products:
            variant = p.get("variants", [{}])[0] if p.get("variants") else {}
            products.append({
                "id": str(p.get("id", "")),
                "name": p.get("title", ""),
                "price": float(variant.get("price", p.get("price", 0)) or 0),
                "cost": float(variant.get("cost", p.get("cost", 0)) or 0),
                "compare_at_price": float(variant.get("compare_at_price", 0) or 0),
                "weight": float(variant.get("weight", p.get("weight", 0)) or 0),
                "category": p.get("product_type", ""),
                "tags": p.get("tags", "").split(", ") if isinstance(p.get("tags"), str) else [],
                "status": p.get("status", "active"),
                "inventory_quantity": int(variant.get("inventory_quantity", 0) or 0),
                "vendor": p.get("vendor", ""),
                "created_at": p.get("created_at", ""),
            })
        return products

    @staticmethod
    def _normalize_orders(raw_orders: list[dict]) -> list[dict[str, Any]]:
        orders = []
        for o in raw_orders:
            orders.append({
                "id": str(o.get("id", "")),
                "total": float(o.get("total_price", 0) or 0),
                "subtotal": float(o.get("subtotal_price", 0) or 0),
                "status": o.get("financial_status", ""),
                "fulfillment_status": o.get("fulfillment_status", ""),
                "items": len(o.get("line_items", [])),
                "customer_id": str(o.get("customer", {}).get("id", "")),
                "created_at": o.get("created_at", ""),
            })
        return orders

    @staticmethod
    def _normalize_customers(raw_customers: list[dict]) -> list[dict[str, Any]]:
        customers = []
        for c in raw_customers:
            customers.append({
                "id": str(c.get("id", "")),
                "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                "email": c.get("email", ""),
                "orders": int(c.get("orders_count", 0) or 0),
                "total_spent": float(c.get("total_spent", 0) or 0),
                "created_at": c.get("created_at", ""),
                "tags": c.get("tags", "").split(", ") if isinstance(c.get("tags"), str) else [],
            })
        return customers

    # --- Mock data fallbacks removed (see ShopifyBridgeUnavailable) ---
