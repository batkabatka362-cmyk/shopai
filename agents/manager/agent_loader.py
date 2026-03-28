"""Agent Loader — dynamically loads agent configurations."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("agents.loader")


class AgentLoader:
    def load_config(self, config_path: str) -> dict[str, Any]:
        logger.info("Loading agent config: %s", config_path)
        return {}

    def load_from_dict(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"status": "loaded", "config": config}
