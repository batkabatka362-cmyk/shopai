"""Negotiation — agent negotiation logic for resource/task allocation."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("agents.negotiation")


class Negotiation:
    def negotiate(self, agents: list[str], resource: dict[str, Any]) -> dict[str, Any]:
        if not agents:
            return {"winner": None, "reason": "no agents"}
        winner = agents[0]
        logger.info("Negotiation won by %s for resource %s", winner, resource.get("name", ""))
        return {"winner": winner, "resource": resource}
