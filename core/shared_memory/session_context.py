"""SessionContext — persistent context across engine runs within a session.

When user runs multiple tasks in one session, context accumulates:
  - Product data from product_selection stays available for pricing engine
  - Customer segments from segmentation feed into personalization
  - All engines in a session share the same context pool
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("shared_memory.session")


class SessionContext:
    """Shared context pool for a user session."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._context: dict[str, Any] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._created_at = time.time()

    @property
    def session_id(self) -> str:
        return self._session_id

    def store(self, engine_name: str, key: str, value: Any) -> None:
        """Store a value in session context from an engine."""
        with self._lock:
            ns_key = f"{engine_name}.{key}"
            self._context[ns_key] = copy.deepcopy(value)
            # Also store without namespace for cross-engine access
            self._context[key] = copy.deepcopy(value)
            self._history.append({
                "action": "store",
                "engine": engine_name,
                "key": key,
                "timestamp": time.time(),
            })

    def store_result(self, engine_name: str, result: dict[str, Any]) -> None:
        """Store full engine result for cross-engine access."""
        with self._lock:
            self._context[f"_result_{engine_name}"] = copy.deepcopy(result)
            # Promote important fields to top level
            for key in ("selected_products", "scored_products", "customer_segments",
                        "pricing_recommendations", "rankings", "campaign_plan",
                        "inventory_analysis", "keyword_strategy"):
                if key in result:
                    self._context[key] = copy.deepcopy(result[key])

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from session context."""
        with self._lock:
            return copy.deepcopy(self._context.get(key, default))

    def get_for_engine(self, engine_name: str) -> dict[str, Any]:
        """Get all context relevant to an engine."""
        with self._lock:
            relevant = {}
            for key, value in self._context.items():
                if key.startswith("_result_"):
                    continue  # Skip full results, too heavy
                relevant[key] = copy.deepcopy(value)
            return relevant

    def get_prior_result(self, engine_name: str) -> dict[str, Any] | None:
        """Get a specific engine's prior result."""
        with self._lock:
            result = self._context.get(f"_result_{engine_name}")
            return copy.deepcopy(result) if result else None

    def merge(self, data: dict[str, Any], source: str = "external") -> None:
        """Merge external data into session context."""
        with self._lock:
            for key, value in data.items():
                if not key.startswith("_"):
                    self._context[key] = copy.deepcopy(value)

    def snapshot(self) -> dict[str, Any]:
        """Get a snapshot of current context (excluding heavy results)."""
        with self._lock:
            return {
                "session_id": self._session_id,
                "created_at": self._created_at,
                "context_keys": [k for k in self._context if not k.startswith("_result_")],
                "result_engines": [k.replace("_result_", "") for k in self._context if k.startswith("_result_")],
                "history_count": len(self._history),
            }

    def clear(self) -> None:
        """Clear session context."""
        with self._lock:
            self._context.clear()
            self._history.clear()
