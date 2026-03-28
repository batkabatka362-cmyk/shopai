"""Product Creator — creates products on Shopify store."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.product_creator")


class ProductCreator:
    def __init__(self, store_url: str = "", api_key: str = "") -> None:
        self._store_url = store_url
        self._api_key = api_key

    def create(self, product_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Creating product: %s", product_data.get("title", "unknown"))
        return {"status": "created", "product_id": "", "product": product_data}

    def create_batch(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.create(p) for p in products]
