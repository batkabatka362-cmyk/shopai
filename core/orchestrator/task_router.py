from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from engines.registry import list_engines

logger = get_logger("orchestrator.task_router")

# Alias map: human-friendly task names → engine names
TASK_ALIASES: dict[str, str] = {
    "find_product": "product_selection",
    "analyze_market": "market_research",
    "set_price": "pricing",
    "generate_content": "content_generation",
    "launch_campaign": "marketing",
    "run_analytics": "analytics",
    "optimize_funnel": "funnel",
    "manage_inventory": "inventory",
}

# All 75 engines: engine_name routes directly to itself
ENGINE_MAP: dict[str, str] = {name: name for name in list_engines()}
ENGINE_MAP.update(TASK_ALIASES)


class TaskRouter:
    """Routes incoming tasks to the appropriate engine based on task type."""

    def __init__(self, engine_config: dict[str, Any] | None = None) -> None:
        self._engine_config = engine_config or {}
        self._custom_routes: dict[str, str] = {}

    def register_route(self, task_type: str, engine_name: str) -> None:
        self._custom_routes[task_type] = engine_name
        logger.info("Registered custom route: %s -> %s", task_type, engine_name)

    def resolve(self, task_type: str) -> str | None:
        if task_type in self._custom_routes:
            engine = self._custom_routes[task_type]
        elif task_type in ENGINE_MAP:
            engine = ENGINE_MAP[task_type]
        else:
            logger.warning("No route found for task_type=%s", task_type)
            return None

        engine_cfg = self._engine_config.get(engine, {})
        if not engine_cfg.get("enabled", True):
            logger.warning("Engine %s is disabled", engine)
            return None

        logger.info("Resolved task_type=%s -> engine=%s", task_type, engine)
        return engine

    def list_routes(self) -> dict[str, str]:
        routes = dict(ENGINE_MAP)
        routes.update(self._custom_routes)
        return routes
