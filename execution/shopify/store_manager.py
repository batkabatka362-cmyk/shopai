"""Store Manager — manages Shopify store settings and configuration."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.store_manager")


class StoreManager:
    def __init__(self, store_url: str = "", api_key: str = "") -> None:
        self._store_url = store_url
        self._api_key = api_key

    def get_store_info(self) -> dict[str, Any]:
        logger.info("Fetching store info")
        return {"store_url": self._store_url, "status": "active"}

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        logger.info("Updating store settings")
        return {"status": "updated", "settings": settings}
