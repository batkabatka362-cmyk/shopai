"""Campaign Manager — manages running marketing campaigns."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.campaign_manager")


class CampaignManager:
    def __init__(self) -> None:
        self._campaigns: dict[str, dict[str, Any]] = {}

    def register(self, campaign_id: str, data: dict[str, Any]) -> None:
        self._campaigns[campaign_id] = {**data, "status": "active"}

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        return self._campaigns.get(campaign_id)

    def list_active(self) -> list[str]:
        return [cid for cid, c in self._campaigns.items() if c.get("status") == "active"]

    def stop(self, campaign_id: str) -> None:
        if campaign_id in self._campaigns:
            self._campaigns[campaign_id]["status"] = "stopped"
