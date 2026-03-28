from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .context_builder import ContextBuilder
from .context_store import ContextStore
from .context_switcher import ContextSwitcher

logger = get_logger("context.manager")


class ContextManager:
    """High-level context management coordinating builder, store, and switcher."""

    def __init__(self) -> None:
        self.builder = ContextBuilder()
        self.store = ContextStore()
        self.switcher = ContextSwitcher()

    def create_context(
        self,
        task_type: str,
        params: dict[str, Any] | None = None,
        session_data: dict[str, Any] | None = None,
        switch: bool = True,
    ) -> dict[str, Any]:
        context = self.builder.build(task_type, params, session_data)
        context_id = context["context_id"]
        self.store.save(context_id, context)
        if switch:
            self.switcher.switch_to(context_id)
        return context

    def get_active_context(self) -> dict[str, Any] | None:
        active_id = self.switcher.active_context_id
        if active_id is None:
            return None
        return self.store.load(active_id)

    def switch_context(self, context_id: str) -> str | None:
        if self.store.load(context_id) is None:
            logger.warning("Cannot switch to unknown context %s", context_id)
            return None
        return self.switcher.switch_to(context_id)

    def pop_context(self) -> str | None:
        return self.switcher.switch_back()

    def delete_context(self, context_id: str) -> bool:
        return self.store.delete(context_id)

    def list_contexts(self) -> list[str]:
        return self.store.list_ids()
