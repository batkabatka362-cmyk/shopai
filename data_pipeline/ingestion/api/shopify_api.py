"""Shopify API — fetches store, product, and order data from Shopify."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.shopify_api")


class ShopifyAPI:
    """Fetches structured data from Shopify stores."""

    def __init__(self, store_url: str = "", api_key: str = "") -> None:
        self._store_url = store_url
        self._api_key = api_key

    def fetch_products(self, limit: int = 50) -> list[dict[str, Any]]:
        logger.info("Fetching products (limit=%d)", limit)
        return []  # Placeholder for actual API call

    def fetch_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        logger.info("Fetching orders (limit=%d)", limit)
        return []

    def fetch_customers(self, limit: int = 50) -> list[dict[str, Any]]:
        logger.info("Fetching customers (limit=%d)", limit)
        return []

    def fetch_store_info(self) -> dict[str, Any]:
        logger.info("Fetching store info")
        return {}
