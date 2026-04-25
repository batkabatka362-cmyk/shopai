"""ShopifyLiveConnector — production Shopify API connection manager.

Handles: authentication, rate limiting, pagination, error recovery.
Wraps ShopifyBridge with production concerns.
"""
from __future__ import annotations

import os
import time
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("shopify.connector")


class ShopifyLiveConnector:
    """Production Shopify connection with rate limiting and error recovery."""

    def __init__(self) -> None:
        self._shop_url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        # D1: resolve through ExpiringTokenAuth when OAuth env is
        # set so we auto-refresh on 60-min expiry; fall back to
        # the legacy static SHOPAI_SHOPIFY_KEY when it isn't.
        try:
            from core.auth.token_resolver import (
                resolve_access_token,
            )
            self._api_key = resolve_access_token(
                self._shop_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "token resolver failed, using legacy: %s",
                exc,
            )
            self._api_key = os.environ.get(
                "SHOPAI_SHOPIFY_KEY", "",
            )
        self._connected = False
        self._last_call = 0.0
        self._call_count = 0
        self._rate_limit = 2  # calls per second (Shopify allows 2/sec)
        self._lock = threading.Lock()
        self._error_count = 0
        self._max_errors = 5

    @property
    def is_configured(self) -> bool:
        return bool(self._shop_url and self._api_key)

    def connect(self) -> dict[str, Any]:
        """Test connection to Shopify."""
        if not self.is_configured:
            return {"connected": False, "reason": "Missing SHOPAI_SHOPIFY_URL or SHOPAI_SHOPIFY_KEY",
                    "fix": "Set environment variables or add to .env file"}

        try:
            from core.bridge.shopify_bridge import ShopifyBridge
            bridge = ShopifyBridge(self._shop_url, self._api_key)
            result = bridge.connect()
            self._connected = result.get("connected", False)
            return result
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    def fetch_store_data(self) -> dict[str, Any]:
        """Fetch full store data for all engines."""
        from core.bridge.shopify_bridge import ShopifyBridge
        bridge = ShopifyBridge(self._shop_url, self._api_key)

        if self._connected:
            bridge.connect()

        products = self._rate_limited_call(bridge.fetch_products)
        orders = self._rate_limited_call(bridge.fetch_orders)
        customers = self._rate_limited_call(bridge.fetch_customers)

        return {
            "products": products,
            "order_data": orders,
            "customer_data": customers,
            "store_url": self._shop_url,
            "fetched_at": time.time(),
            "source": "shopify_live" if self._connected else "mock",
        }

    def _rate_limited_call(self, func, *args, **kwargs) -> Any:
        """Call with rate limiting (max 2 calls/sec for Shopify)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < 1.0 / self._rate_limit:
                time.sleep(1.0 / self._rate_limit - elapsed)
            self._last_call = time.monotonic()
            self._call_count += 1

        try:
            result = func(*args, **kwargs)
            self._error_count = 0
            return result
        except Exception as exc:
            self._error_count += 1
            logger.error("Shopify API call failed (%d/%d): %s", self._error_count, self._max_errors, exc)
            if self._error_count >= self._max_errors:
                logger.error("Max errors reached — falling back to mock data")
                self._connected = False
            return []

    def get_status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured,
            "connected": self._connected,
            "shop_url": self._shop_url[:20] + "..." if self._shop_url else "",
            "api_calls": self._call_count,
            "errors": self._error_count,
            "rate_limit": f"{self._rate_limit}/sec",
        }
