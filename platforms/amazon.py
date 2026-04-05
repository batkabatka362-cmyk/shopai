"""Amazon Adapter — manage Amazon seller account with same AI.

Uses Amazon SP-API (Selling Partner API) structure.
Requires: refresh_token, client_id, client_secret, marketplace_id.
"""
from __future__ import annotations
import json
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("platform.amazon")


class AmazonAdapter:
    """Amazon Selling Partner API adapter."""

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._token: str = ""

    def configure(self, refresh_token: str, client_id: str,
                  client_secret: str, marketplace_id: str = "ATVPDKIKX0DER") -> None:
        self._credentials = {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "marketplace_id": marketplace_id,
        }

    def get_listings(self, limit: int = 50) -> list[dict]:
        """Get product listings."""
        # SP-API call would go here
        if not self._credentials.get("refresh_token"):
            return []
        # Placeholder — actual implementation needs SP-API auth flow
        return []

    def get_orders(self, days: int = 7) -> list[dict]:
        if not self._credentials.get("refresh_token"):
            return []
        return []

    def update_price(self, asin: str, price: float) -> dict:
        if not self._credentials.get("refresh_token"):
            return {"error": "not_configured"}
        return {"status": "would_update", "asin": asin, "price": price}

    def update_inventory(self, sku: str, quantity: int) -> dict:
        if not self._credentials.get("refresh_token"):
            return {"error": "not_configured"}
        return {"status": "would_update", "sku": sku, "quantity": quantity}

    @staticmethod
    def normalize_product(listing: dict) -> dict:
        """Normalize Amazon listing to ShopAI format."""
        return {
            "id": listing.get("asin", listing.get("sku", "")),
            "name": listing.get("title", ""),
            "price": float(listing.get("price", {}).get("amount", 0)),
            "cost": 0,
            "images": [listing.get("main_image", {}).get("link", "")],
            "inventory_quantity": listing.get("fulfillable_quantity", 0),
            "platform": "amazon",
        }

    def get_stats(self) -> dict:
        return {
            "platform": "amazon",
            "configured": bool(self._credentials.get("refresh_token")),
            "marketplace": self._credentials.get("marketplace_id", ""),
        }


_instance = None
def get_amazon():
    global _instance
    if _instance is None:
        _instance = AmazonAdapter()
    return _instance
