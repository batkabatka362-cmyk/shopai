"""Amazon Adapter — placeholder for Amazon Selling Partner API.

This module previously pretended to be an Amazon SP-API client.
Every read returned ``[]`` even when credentials were present, and
every write returned ``{"status": "would_update", ...}`` without
ever touching the SP-API. Callers that treated those results as
successful executions were making decisions against empty data
and phantom "updates" that never reached Amazon.

The adapter layer (``core/adapters/``) will carry the real SP-API
integration once it is wired in. Until then every method on this
class raises ``NotImplementedError`` with a clear
"adapter_required" sentinel so the controller's cycle loop can
detect the gap and route Amazon work elsewhere instead of silently
burning decisions on a fake backend.
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("platform.amazon")


class AmazonNotImplementedError(NotImplementedError):
    """Raised for every Amazon SP-API operation until the real
    adapter lands. Subclass of ``NotImplementedError`` so existing
    ``except NotImplementedError`` handlers keep working."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"Amazon SP-API adapter not implemented "
            f"(operation={operation!r}). "
            f"Wire the real SP-API via core/adapters/ before calling.",
        )
        self.operation = operation
        self.status = "adapter_required"


class AmazonAdapter:
    """Amazon Selling Partner API adapter — **stub only**.

    Every read/write raises ``AmazonNotImplementedError``. ``configure``
    still stores credentials so the future real adapter can pick them
    up without a configuration round-trip.
    """

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
        """Get product listings. Always raises — no real SP-API."""
        raise AmazonNotImplementedError("get_listings")

    def get_orders(self, days: int = 7) -> list[dict]:
        """Get recent orders. Always raises — no real SP-API."""
        raise AmazonNotImplementedError("get_orders")

    def update_price(self, asin: str, price: float) -> dict:
        """Update ASIN price. Always raises — no real SP-API."""
        raise AmazonNotImplementedError("update_price")

    def update_inventory(self, sku: str, quantity: int) -> dict:
        """Update SKU stock. Always raises — no real SP-API."""
        raise AmazonNotImplementedError("update_inventory")

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
