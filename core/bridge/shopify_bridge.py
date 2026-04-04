"""ShopifyBridge — connects ShopAI engines to real Shopify store data.

Data flow:
  1. Try DB cache (fast, always available)
  2. If stale/missing → fetch from Shopify API → store in DB
  3. Fallback to mock data only if nothing else works

Requires: SHOPAI_SHOPIFY_URL and SHOPAI_SHOPIFY_KEY env vars.
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("bridge.shopify")


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

    def fetch_products(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch products: DB cache → live API → mock."""
        # Try DB cache first
        cached = self._read_cache("products", limit)
        if cached:
            return cached

        # Try live API
        if self._connected and self._api:
            try:
                raw = self._api.fetch_products(self._shop_url, self._api_key)
                products = self._normalize_products(raw.get("products", [])[:limit])
                self._write_cache("products", products)
                return products
            except Exception as exc:
                logger.error("Shopify fetch_products failed: %s", exc)

        return self._mock_products()

    def fetch_orders(self, days_back: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch orders: DB cache → live API → mock."""
        cached = self._read_cache("orders", limit)
        if cached:
            return cached

        if self._connected and self._api:
            try:
                raw = self._api.fetch_orders(self._shop_url, self._api_key, days_back=days_back)
                orders = self._normalize_orders(raw.get("orders", [])[:limit])
                self._write_cache("orders", orders)
                return orders
            except Exception as exc:
                logger.error("Shopify fetch_orders failed: %s", exc)

        return self._mock_orders()

    def fetch_customers(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch customers: DB cache → live API → mock."""
        cached = self._read_cache("customers", limit)
        if cached:
            return cached

        if self._connected and self._api:
            try:
                raw = self._api.fetch_customers(self._shop_url, self._api_key)
                customers = self._normalize_customers(raw.get("customers", [])[:limit])
                self._write_cache("customers", customers)
                return customers
            except Exception as exc:
                logger.error("Shopify fetch_customers failed: %s", exc)

        return self._mock_customers()

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
        except Exception:
            pass

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
        except Exception:
            pass
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

    # --- Mock data (last resort fallback) ---

    @staticmethod
    def _mock_products() -> list[dict[str, Any]]:
        return [
            {"id": "1", "name": "Wireless Earbuds Pro", "price": 49.99, "cost": 15, "weight": 0.1, "category": "electronics",
             "inventory_quantity": 150, "compare_at_price": 69.99, "rating": 4.6, "reviews": 280, "search_volume": 12000, "competition": 4},
            {"id": "2", "name": "Premium Yoga Mat", "price": 39.99, "cost": 12, "weight": 2.0, "category": "fitness",
             "inventory_quantity": 80, "compare_at_price": 0, "rating": 4.3, "reviews": 150, "search_volume": 8500, "competition": 6},
            {"id": "3", "name": "LED Desk Lamp", "price": 34.99, "cost": 18, "weight": 1.5, "category": "home",
             "inventory_quantity": 45, "compare_at_price": 44.99, "rating": 4.1, "reviews": 95, "search_volume": 6200, "competition": 5},
            {"id": "4", "name": "Phone Case Ultra", "price": 19.99, "cost": 3, "weight": 0.05, "category": "accessories",
             "inventory_quantity": 300, "compare_at_price": 0, "rating": 4.0, "reviews": 420, "search_volume": 15000, "competition": 8},
            {"id": "5", "name": "Resistance Bands Set", "price": 24.99, "cost": 5, "weight": 0.3, "category": "fitness",
             "inventory_quantity": 200, "compare_at_price": 34.99, "rating": 4.7, "reviews": 310, "search_volume": 9800, "competition": 3},
        ]

    @staticmethod
    def _mock_orders() -> list[dict[str, Any]]:
        return [
            {"id": "1001", "total": 89.98, "subtotal": 84.98, "status": "paid", "items": 2, "customer_id": "c1"},
            {"id": "1002", "total": 49.99, "subtotal": 49.99, "status": "paid", "items": 1, "customer_id": "c2"},
            {"id": "1003", "total": 124.97, "subtotal": 119.97, "status": "paid", "items": 3, "customer_id": "c1"},
            {"id": "1004", "total": 34.99, "subtotal": 34.99, "status": "refunded", "items": 1, "customer_id": "c3"},
            {"id": "1005", "total": 64.98, "subtotal": 59.98, "status": "paid", "items": 2, "customer_id": "c4"},
        ]

    @staticmethod
    def _mock_customers() -> list[dict[str, Any]]:
        return [
            {"id": "c1", "name": "Alice Kim", "email": "alice@example.com", "orders": 8, "total_spent": 650,
             "days_since_last_order": 5, "tags": ["vip", "repeat"], "created_at": "2024-01-15"},
            {"id": "c2", "name": "Bob Park", "email": "bob@example.com", "orders": 1, "total_spent": 49.99,
             "days_since_last_order": 90, "tags": ["new"], "created_at": "2025-11-20"},
            {"id": "c3", "name": "Carol Lee", "email": "carol@example.com", "orders": 3, "total_spent": 180,
             "days_since_last_order": 35, "tags": ["returning"], "created_at": "2025-06-10"},
            {"id": "c4", "name": "Dave Song", "email": "dave@example.com", "orders": 0, "total_spent": 0,
             "days_since_last_order": 0, "tags": ["lead"], "created_at": "2026-03-01"},
        ]
