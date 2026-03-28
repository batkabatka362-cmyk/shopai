from __future__ import annotations

from typing import Any

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("context.builder")


class ContextBuilder:
    """Builds context objects from task parameters and system state."""

    def __init__(self) -> None:
        self._defaults: dict[str, Any] = {}

    def set_defaults(self, defaults: dict[str, Any]) -> None:
        self._defaults = defaults

    def build(
        self,
        task_type: str,
        params: dict[str, Any] | None = None,
        session_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = {
            "context_id": generate_id("ctx"),
            "task_type": task_type,
            "created_at": timestamp_now(),
            **self._defaults,
        }
        if params:
            context["params"] = params
        if session_data:
            context["session"] = session_data
        logger.info("Built context %s for task_type=%s", context["context_id"], task_type)
        return context

    def extend(self, base_context: dict[str, Any], extras: dict[str, Any]) -> dict[str, Any]:
        merged = {**base_context, **extras}
        merged["extended_at"] = timestamp_now()
        return merged
