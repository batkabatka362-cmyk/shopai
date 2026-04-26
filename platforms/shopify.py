"""Shopify Adapter — manage Shopify stores with the same multi-platform
interface used by ``WooCommerceAdapter`` and ``AmazonAdapter``.

This is a thin facade over the existing audited Shopify modules:

  * ``data_pipeline.ingestion.api.shopify_api.ShopifyAPI`` for reads
    (handles pagination, ``Retry-After`` parsing, and 429/5xx retry).
  * ``execution.shopify.product_updater.ProductUpdater`` for writes
    (PUT product/variant, POST inventory_levels/set).

Goals:
  * Same call surface as ``WooCommerceAdapter`` so callers iterating over
    platforms don't special-case Shopify.
  * Reuse the existing HTTP/auth/pagination code instead of reimplementing
    it — that code is the audited path used by the engines and the bridge.
  * No silent mock fallbacks. If credentials are missing or the live API
    fails, return an empty list (reads) or an explicit ``{"status":
    "error", ...}`` dict (writes); never fabricate data.
"""
from __future__ import annotations

import os
from typing import Any

from utils.logger import get_logger

logger = get_logger("platform.shopify")


def _normalize_shop_url(raw: str) -> str:
    """Strip scheme and trailing slash from a Shopify shop URL.

    Mirrors ``data_pipeline.ingestion.api.shopify_api._normalize_shop_url``
    so the adapter and the underlying client agree on the canonical form
    before either of them builds a request URL.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().rstrip("/")
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s


class ShopifyAdapter:
    """Shopify Admin REST API adapter (2024-01).

    Authentication can come from either:

      * **Static token** (legacy custom-app, ``shpat_...``) — pass
        ``access_token`` or set ``SHOPAI_SHOPIFY_KEY``.
      * **OAuth client credentials** (Dev Dashboard apps, 2026+) —
        pass ``client_id`` + ``client_secret`` or set
        ``SHOPAI_SHOPIFY_CLIENT_ID`` + ``SHOPAI_SHOPIFY_CLIENT_SECRET``.
        The adapter will lazily mint a 24h token via
        ``core.auth.shopify_auth.ShopifyAuth`` and refresh on its own.

    If both are provided, the static token wins (so callers can pin a
    specific token for a single run without disabling rotation
    elsewhere in the process).
    """

    def __init__(
        self,
        shop_url: str = "",
        access_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self._shop_url = _normalize_shop_url(shop_url) or _normalize_shop_url(
            os.environ.get("SHOPAI_SHOPIFY_URL", "")
        )
        self._static_token = access_token or os.environ.get("SHOPAI_SHOPIFY_KEY", "")
        self._client_id = client_id or os.environ.get("SHOPAI_SHOPIFY_CLIENT_ID", "")
        self._client_secret = (
            client_secret or os.environ.get("SHOPAI_SHOPIFY_CLIENT_SECRET", "")
        )
        self._auth = None  # lazily-built ShopifyAuth

    def configure(
        self,
        shop_url: str,
        access_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self._shop_url = _normalize_shop_url(shop_url)
        self._static_token = access_token if isinstance(access_token, str) else ""
        self._client_id = client_id if isinstance(client_id, str) else ""
        self._client_secret = client_secret if isinstance(client_secret, str) else ""
        self._auth = None

    @property
    def is_configured(self) -> bool:
        if not self._shop_url:
            return False
        if self._static_token:
            return True
        return bool(self._client_id and self._client_secret)

    def _resolve_token(self) -> str:
        """Return a usable Admin API access token, or ``""`` if none.

        Priority: static token > client_credentials grant via ShopifyAuth.
        Token-refresh failures are swallowed and the cached token (which
        may be empty) is returned so the read paths return ``[]`` instead
        of crashing.
        """
        if self._static_token:
            return self._static_token
        if not (self._client_id and self._client_secret and self._shop_url):
            return ""
        if self._auth is None:
            try:
                from core.auth.shopify_auth import ShopifyAuth
            except Exception as exc:  # noqa: BLE001
                logger.error("ShopifyAuth import failed: %s", exc)
                return ""
            self._auth = ShopifyAuth(self._shop_url, self._client_id, self._client_secret)
        try:
            return self._auth.get_token()
        except Exception as exc:  # noqa: BLE001
            logger.error("Shopify token refresh failed: %s", exc)
            return ""

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    def get_products(self, limit: int = 50) -> list[dict]:
        api, token = self._api()
        if api is None or not token:
            return []
        try:
            result = api.fetch_products(self._shop_url, token)
        except Exception as exc:  # noqa: BLE001
            logger.error("Shopify get_products failed: %s", exc)
            return []
        records = result.get("products", []) if isinstance(result, dict) else []
        return [self._normalize_product(p) for p in records[: max(0, int(limit))]]

    def get_orders(self, limit: int = 50, days_back: int = 30) -> list[dict]:
        api, token = self._api()
        if api is None or not token:
            return []
        try:
            result = api.fetch_orders(self._shop_url, token, days_back=days_back)
        except Exception as exc:  # noqa: BLE001
            logger.error("Shopify get_orders failed: %s", exc)
            return []
        records = result.get("orders", []) if isinstance(result, dict) else []
        return [self._normalize_order(o) for o in records[: max(0, int(limit))]]

    def get_customers(self, limit: int = 50) -> list[dict]:
        api, token = self._api()
        if api is None or not token:
            return []
        try:
            result = api.fetch_customers(self._shop_url, token)
        except Exception as exc:  # noqa: BLE001
            logger.error("Shopify get_customers failed: %s", exc)
            return []
        records = result.get("customers", []) if isinstance(result, dict) else []
        return [self._normalize_customer(c) for c in records[: max(0, int(limit))]]

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def update_product(self, product_id: str, fields: dict) -> dict:
        if not self.is_configured:
            return {"status": "error", "error": "shopify_not_configured"}
        token = self._resolve_token()
        if not token:
            return {"status": "error", "error": "token_unavailable"}
        updater = self._updater()
        if updater is None:
            return {"status": "error", "error": "updater_unavailable"}
        return updater.update_product(self._shop_url, token, product_id, fields)

    def update_price(self, product_id: str, variant_id: str, new_price: float) -> dict:
        if not self.is_configured:
            return {"status": "error", "error": "shopify_not_configured"}
        token = self._resolve_token()
        if not token:
            return {"status": "error", "error": "token_unavailable"}
        updater = self._updater()
        if updater is None:
            return {"status": "error", "error": "updater_unavailable"}
        return updater.update_price(
            self._shop_url, token, product_id, variant_id, new_price
        )

    def update_inventory(
        self, inventory_item_id: str, location_id: str, quantity: int
    ) -> dict:
        if not self.is_configured:
            return {"status": "error", "error": "shopify_not_configured"}
        token = self._resolve_token()
        if not token:
            return {"status": "error", "error": "token_unavailable"}
        updater = self._updater()
        if updater is None:
            return {"status": "error", "error": "updater_unavailable"}
        return updater.update_inventory(
            self._shop_url, token, inventory_item_id, location_id, quantity
        )

    def get_stats(self) -> dict:
        return {
            "platform": "shopify",
            "configured": self.is_configured,
            "shop": self._shop_url,
        }

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _api(self):
        """Return ``(ShopifyAPI, token)`` or ``(None, "")`` if either
        instantiation fails or no token is available right now."""
        if not self.is_configured:
            return None, ""
        token = self._resolve_token()
        if not token:
            return None, ""
        try:
            from data_pipeline.ingestion.api.shopify_api import ShopifyAPI
        except Exception as exc:  # noqa: BLE001
            logger.error("ShopifyAPI import failed: %s", exc)
            return None, ""
        return ShopifyAPI(self._shop_url, token), token

    def _updater(self):
        try:
            from execution.shopify.product_updater import ProductUpdater
        except Exception as exc:  # noqa: BLE001
            logger.error("ProductUpdater import failed: %s", exc)
            return None
        return ProductUpdater()

    # ------------------------------------------------------------------ #
    # Normalizers — produce the same shape as WooCommerceAdapter so       #
    # callers iterating over multi-platform data don't branch on          #
    # ``record["platform"]`` to read a price.                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_product(p: dict) -> dict:
        variant = (p.get("variants") or [{}])[0]
        tags = p.get("tags", "")
        if isinstance(tags, list):
            tags_str = ", ".join(str(t) for t in tags)
        else:
            tags_str = tags or ""
        return {
            "id": str(p.get("id", "")),
            "name": p.get("title", ""),
            "price": float(variant.get("price", 0) or 0),
            "cost": float(variant.get("cost", 0) or 0),
            "compare_at_price": float(variant.get("compare_at_price", 0) or 0),
            "description": p.get("body_html", ""),
            "tags": tags_str,
            "category": p.get("product_type", ""),
            "images": [img.get("src", "") for img in (p.get("images") or [])],
            "inventory_quantity": int(variant.get("inventory_quantity", 0) or 0),
            "vendor": p.get("vendor", ""),
            "variant_id": str(variant.get("id", "")),
            "platform": "shopify",
        }

    @staticmethod
    def _normalize_order(o: dict) -> dict:
        return {
            "id": str(o.get("id", "")),
            "total": float(o.get("total_price", 0) or 0),
            "subtotal": float(o.get("subtotal_price", 0) or 0),
            "status": o.get("financial_status", "") or "",
            "fulfillment_status": o.get("fulfillment_status", "") or "",
            "customer_id": str((o.get("customer") or {}).get("id", "")),
            "items": len(o.get("line_items") or []),
            "created_at": o.get("created_at", ""),
            "platform": "shopify",
        }

    @staticmethod
    def _normalize_customer(c: dict) -> dict:
        first = c.get("first_name", "") or ""
        last = c.get("last_name", "") or ""
        return {
            "id": str(c.get("id", "")),
            "name": f"{first} {last}".strip(),
            "email": c.get("email", ""),
            "orders": int(c.get("orders_count", 0) or 0),
            "total_spent": float(c.get("total_spent", 0) or 0),
            "created_at": c.get("created_at", ""),
            "platform": "shopify",
        }


_instance: ShopifyAdapter | None = None


def get_shopify() -> ShopifyAdapter:
    """Return the process-wide ShopifyAdapter singleton."""
    global _instance
    if _instance is None:
        _instance = ShopifyAdapter()
    return _instance
