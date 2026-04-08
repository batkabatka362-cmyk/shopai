"""DataProvider — unified data source for all engines.

Engines call DataProvider to get data. DataProvider reads from:
1. Local DB cache (fast, always available)
2. Live Shopify API (if cache is stale or missing)

If both fail the provider returns an **empty** result with
``source="empty"`` instead of silently substituting a hardcoded
mock dataset. Pre-cleanup this module shipped 5 fake products, 5
fake orders, and 4 fake customers that every engine treated as
real — inventory checks, revenue forecasts, customer segmentation
and pricing decisions were quietly trained on fiction whenever a
store was not yet wired up. Callers now have to either:

* inspect ``source == "empty"`` and short-circuit, or
* catch ``ValueError`` from ``get_products/orders/customers`` and
  decide what to do explicitly.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("data_provider")

# Cache staleness threshold (seconds)
_CACHE_TTL = 600  # 10 minutes


class DataProvider:
    """Unified data provider for all ShopAI engines."""

    def __init__(self, store_manager: Any = None, cache_ttl: int = _CACHE_TTL) -> None:
        from data_pipeline.store.store_manager import StoreManager
        self._sm: StoreManager = store_manager or StoreManager()
        self._cache_ttl = cache_ttl

    # ── Main interface (what engines call) ───────────────────

    def get_data_for_engine(self, engine_name: str, store_id: str = "") -> dict[str, Any]:
        """Get the right data for a specific engine.

        Returns engine-ready dict with products, orders, customers as needed.
        Falls back to mock data if no real data available.
        """
        sid = store_id or self._sm.active_store_id

        # Determine what data this engine needs
        needs = self._engine_data_needs(engine_name)
        data: dict[str, Any] = {"store_id": sid, "source": "database"}

        if "products" in needs:
            products = self._get_products(sid)
            data["products"] = products

        if "orders" in needs:
            orders = self._get_orders(sid)
            data["order_data"] = orders

        if "customers" in needs:
            customers = self._get_customers(sid)
            data["customer_data"] = customers

        if "analytics" in needs:
            data["analytics"] = self._get_analytics(sid)

        # If we got no data at all, mark the source as "empty"
        # instead of substituting the old 5-product mock dataset.
        # Callers can inspect ``source`` and decide how to react
        # (skip the cycle, raise, or prompt reconnection) — the
        # important change is that the downstream engine sees
        # honest empty lists, not fictional products.
        has_data = any(
            data.get(k) for k in ("products", "order_data", "customer_data")
        )
        if not has_data:
            data["source"] = "empty"
            data.setdefault("products", [])
            data.setdefault("order_data", [])
            data.setdefault("customer_data", [])

        data["fetched_at"] = time.time()
        return data

    def get_products(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._sm.active_store_id
        return self._get_products(sid, **kwargs)

    def get_orders(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._sm.active_store_id
        return self._get_orders(sid, **kwargs)

    def get_customers(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._sm.active_store_id
        return self._get_customers(sid, **kwargs)

    # ── Internal data fetching ───────────────────────────────

    def _get_products(self, store_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if not store_id:
            return []
        try:
            products = self._sm.db.get_products(store_id, **kwargs)
            if products and not self._is_stale(store_id, "products"):
                return products
            # Try live sync if stale
            if self._should_refresh(store_id, "products"):
                self._refresh_products(store_id)
                return self._sm.db.get_products(store_id, **kwargs)
            return products
        except Exception as exc:
            logger.error("Failed to get products for %s: %s", store_id, exc)
            return []

    def _get_orders(self, store_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if not store_id:
            return []
        try:
            orders = self._sm.db.get_orders(store_id, **kwargs)
            if orders and not self._is_stale(store_id, "orders"):
                return orders
            if self._should_refresh(store_id, "orders"):
                self._refresh_orders(store_id)
                return self._sm.db.get_orders(store_id, **kwargs)
            return orders
        except Exception as exc:
            logger.error("Failed to get orders for %s: %s", store_id, exc)
            return []

    def _get_customers(self, store_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if not store_id:
            return []
        try:
            customers = self._sm.db.get_customers(store_id, **kwargs)
            if customers and not self._is_stale(store_id, "customers"):
                return customers
            if self._should_refresh(store_id, "customers"):
                self._refresh_customers(store_id)
                return self._sm.db.get_customers(store_id, **kwargs)
            return customers
        except Exception as exc:
            logger.error("Failed to get customers for %s: %s", store_id, exc)
            return []

    def _get_analytics(self, store_id: str) -> dict[str, Any]:
        """Get computed analytics from stored data."""
        stats = self._sm.db.get_store_stats(store_id)
        snapshots = self._sm.db.get_snapshots(store_id, "post_sync", limit=7)
        return {"current": stats, "history": snapshots}

    # ── Live refresh ─────────────────────────────────────────

    def _refresh_products(self, store_id: str) -> None:
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(self._sm)
            sync._sync_products(store_id, self._sm.get_credentials(store_id))
        except Exception as exc:
            logger.warning("Product refresh failed for %s: %s", store_id, exc)

    def _refresh_orders(self, store_id: str) -> None:
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(self._sm)
            sync._sync_orders(store_id, self._sm.get_credentials(store_id))
        except Exception as exc:
            logger.warning("Order refresh failed for %s: %s", store_id, exc)

    def _refresh_customers(self, store_id: str) -> None:
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(self._sm)
            sync._sync_customers(store_id, self._sm.get_credentials(store_id))
        except Exception as exc:
            logger.warning("Customer refresh failed for %s: %s", store_id, exc)

    # ── Cache staleness checks ───────────────────────────────

    def _is_stale(self, store_id: str, data_type: str) -> bool:
        last_sync = self._sm.db.get_last_sync(store_id, data_type)
        if not last_sync:
            return True
        age = time.time() - last_sync.get("created_at", 0)
        return age > self._cache_ttl

    def _should_refresh(self, store_id: str, data_type: str) -> bool:
        """Should we try a live API refresh? Only if we have credentials."""
        creds = self._sm.get_credentials(store_id)
        return bool(creds.get("shop_url") and creds.get("api_key"))

    # ── Engine data mapping ──────────────────────────────────

    @staticmethod
    def _engine_data_needs(engine_name: str) -> set[str]:
        """Determine what data types an engine needs."""
        # Defensive: pre-audit ``engine_name.lower()`` crashed
        # on None / non-string. Audit pass 48.
        if not isinstance(engine_name, str):
            return {"products"}

        product_keywords = {
            "product", "pricing", "price", "catalog", "seo", "description",
            "inventory", "ranking", "optimization", "selection", "upsell",
            "cross_sell", "bundle", "margin", "sourcing", "quality",
        }
        order_keywords = {
            "order", "analytics", "revenue", "demand", "forecast",
            "conversion", "financial", "margin", "sales", "trend",
            "performance", "report", "dashboard",
        }
        customer_keywords = {
            "customer", "segment", "churn", "retention", "loyalty",
            "personalization", "email", "sms", "marketing", "targeting",
            "lifetime", "cohort", "feedback",
        }

        needs: set[str] = set()
        name_lower = engine_name.lower()

        if any(kw in name_lower for kw in product_keywords):
            needs.add("products")
        if any(kw in name_lower for kw in order_keywords):
            needs.add("orders")
        if any(kw in name_lower for kw in customer_keywords):
            needs.add("customers")
        if "analytics" in name_lower or "intelligence" in name_lower:
            needs.add("analytics")

        # Default: give products if nothing matched
        if not needs:
            needs.add("products")

        return needs

    # ── Mock data fallbacks removed ──────────────────────────
    #
    # ``_mock_products/orders/customers`` used to live here and
    # served hardcoded sample data whenever the database was empty
    # and no live Shopify credentials were configured. Engines
    # treated the 5 fake products / 5 fake orders / 4 fake
    # customers as truth, corrupting every decision that touched a
    # freshly-bootstrapped installation. The fallback is gone —
    # the provider now returns empty lists with ``source="empty"``
    # and lets the caller react honestly.
