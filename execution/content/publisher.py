"""Publisher — publishes content to platforms."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.publisher")


class Publisher:
    def publish(self, content: dict[str, Any], platform: str = "shopify") -> dict[str, Any]:
        logger.info("Publishing to %s", platform)
        return {"status": "published", "platform": platform, "content_id": ""}

    def unpublish(self, content_id: str, platform: str = "shopify") -> dict[str, Any]:
        return {"status": "unpublished", "content_id": content_id}
