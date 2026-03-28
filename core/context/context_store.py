from __future__ import annotations

from typing import Any

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("context.store")


class ContextStore:
    """Persistent store for context objects keyed by ID."""

    def __init__(self) -> None:
        self._contexts: dict[str, dict[str, Any]] = {}

    def save(self, context_id: str, data: dict[str, Any]) -> None:
        self._contexts[context_id] = {
            "data": data,
            "updated_at": timestamp_now(),
        }

    def load(self, context_id: str) -> dict[str, Any] | None:
        entry = self._contexts.get(context_id)
        return entry["data"] if entry else None

    def delete(self, context_id: str) -> bool:
        return self._contexts.pop(context_id, None) is not None

    def list_ids(self) -> list[str]:
        return list(self._contexts.keys())

    def clear(self) -> None:
        self._contexts.clear()
