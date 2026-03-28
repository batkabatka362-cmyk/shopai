"""Content Scheduler — schedules content for future publication."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.content_scheduler")


class ContentScheduler:
    def __init__(self) -> None:
        self._schedule: list[dict[str, Any]] = []

    def schedule(self, content: dict[str, Any], publish_at: str) -> dict[str, Any]:
        entry = {"content": content, "publish_at": publish_at, "status": "scheduled"}
        self._schedule.append(entry)
        logger.info("Scheduled content for %s", publish_at)
        return entry

    def get_pending(self) -> list[dict[str, Any]]:
        return [s for s in self._schedule if s["status"] == "scheduled"]
