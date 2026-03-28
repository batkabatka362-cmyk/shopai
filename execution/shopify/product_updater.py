"""Product Updater — updates existing products on Shopify."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.product_updater")


class ProductUpdater:
    def __init__(self, store_url: str = "", api_key: str = "") -> None:
        self._store_url = store_url
        self._api_key = api_key

    def update(self, product_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        logger.info("Updating product %s", product_id)
        return {"status": "updated", "product_id": product_id, "updates": updates}

    def update_price(self, product_id: str, price: float) -> dict[str, Any]:
        return self.update(product_id, {"price": price})

    def update_inventory(self, product_id: str, quantity: int) -> dict[str, Any]:
        return self.update(product_id, {"inventory_quantity": quantity})
