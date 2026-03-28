from __future__ import annotations

from typing import Any

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("memory.manager")


class MemoryManager:
    """Manages short-term and long-term memory stores."""

    def __init__(self) -> None:
        self._short_term: dict[str, dict[str, Any]] = {}
        self._long_term: dict[str, dict[str, Any]] = {}

    def store_short_term(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        self._short_term[key] = {
            "value": value,
            "stored_at": timestamp_now(),
            "ttl_seconds": ttl_seconds,
        }

    def store_long_term(self, key: str, value: Any, tags: list[str] | None = None) -> None:
        self._long_term[key] = {
            "value": value,
            "stored_at": timestamp_now(),
            "tags": tags or [],
        }

    def recall(self, key: str) -> Any | None:
        if key in self._short_term:
            return self._short_term[key]["value"]
        if key in self._long_term:
            return self._long_term[key]["value"]
        return None

    def recall_by_tag(self, tag: str) -> list[tuple[str, Any]]:
        results = []
        for key, entry in self._long_term.items():
            if tag in entry.get("tags", []):
                results.append((key, entry["value"]))
        return results

    def forget_short_term(self, key: str) -> bool:
        return self._short_term.pop(key, None) is not None

    def forget_long_term(self, key: str) -> bool:
        return self._long_term.pop(key, None) is not None

    def clear_short_term(self) -> int:
        count = len(self._short_term)
        self._short_term.clear()
        return count

    def get_stats(self) -> dict[str, int]:
        return {
            "short_term_entries": len(self._short_term),
            "long_term_entries": len(self._long_term),
        }
