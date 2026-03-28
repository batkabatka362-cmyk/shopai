from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("context.switcher")


class ContextSwitcher:
    """Manages transitions between active contexts."""

    def __init__(self) -> None:
        self._active_context_id: str | None = None
        self._context_stack: list[str] = []

    @property
    def active_context_id(self) -> str | None:
        return self._active_context_id

    def switch_to(self, context_id: str) -> str | None:
        previous = self._active_context_id
        if previous:
            self._context_stack.append(previous)
        self._active_context_id = context_id
        logger.info("Switched context: %s -> %s", previous, context_id)
        return previous

    def switch_back(self) -> str | None:
        if not self._context_stack:
            logger.warning("No previous context to switch back to")
            return None
        previous = self._active_context_id
        self._active_context_id = self._context_stack.pop()
        logger.info("Switched back: %s -> %s", previous, self._active_context_id)
        return self._active_context_id

    def get_stack(self) -> list[str]:
        return list(self._context_stack)

    def reset(self) -> None:
        self._active_context_id = None
        self._context_stack.clear()
