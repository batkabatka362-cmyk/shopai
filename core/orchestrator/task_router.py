from __future__ import annotations

from typing import Any

from utils.logger import get_logger

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

# Lazy-loaded engine map — built on first access, not on import
_ENGINE_MAP: dict[str, str] | None = None


def _get_engine_map() -> dict[str, str]:
    global _ENGINE_MAP
    if _ENGINE_MAP is None:
        from engines.registry import list_engines
        _ENGINE_MAP = {name: name for name in list_engines()}
        _ENGINE_MAP.update(TASK_ALIASES)
    return _ENGINE_MAP


class TaskRouter:
    """Routes incoming tasks to the appropriate engine based on task type."""

    def __init__(self, engine_config: dict[str, Any] | None = None) -> None:
        self._engine_config = engine_config or {}
        self._custom_routes: dict[str, str] = {}

    def register_route(self, task_type: str, engine_name: str) -> None:
        self._custom_routes[task_type] = engine_name
        logger.info("Registered custom route: %s -> %s", task_type, engine_name)

    def resolve(self, task_type: str) -> str | None:
        engine_map = _get_engine_map()
        if task_type in self._custom_routes:
            engine = self._custom_routes[task_type]
        elif task_type in engine_map:
            engine = engine_map[task_type]
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
        routes = dict(_get_engine_map())
        routes.update(self._custom_routes)
        return routes
