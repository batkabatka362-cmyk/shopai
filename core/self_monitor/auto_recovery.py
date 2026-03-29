"""AutoRecovery — automatic recovery actions for known failure modes.

SAFE ACTIONS ONLY: restart services, clear caches, retry operations.
NEVER modifies engine code, deletes files, or changes system structure.
All recovery actions are logged and reversible.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("monitor.recovery")


class AutoRecovery:
    """Handles automatic recovery from known failure modes.

    SAFETY RULES:
      - Never delete files or code
      - Never modify engine logic
      - Never change system structure
      - Only perform safe, reversible actions
      - Log every action taken
    """

    def __init__(self) -> None:
        self._actions_log: list[dict[str, Any]] = []
        self._recovery_handlers: dict[str, Any] = {
            "cache_full": self._recover_cache_full,
            "engine_cache_stale": self._recover_engine_cache,
            "high_error_rate": self._recover_high_error_rate,
            "memory_pressure": self._recover_memory_pressure,
        }

    def attempt_recovery(self, failure_type: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Attempt automatic recovery for a known failure type."""
        handler = self._recovery_handlers.get(failure_type)
        if handler is None:
            return {
                "recovered": False,
                "action": "none",
                "reason": f"Unknown failure type: {failure_type}. Manual intervention required.",
            }

        logger.info("Attempting auto-recovery for: %s", failure_type)
        start = time.monotonic()

        try:
            result = handler(context or {})
        except Exception as exc:
            result = {"recovered": False, "action": "failed", "error": str(exc)}

        elapsed = time.monotonic() - start
        result["failure_type"] = failure_type
        result["elapsed_seconds"] = round(elapsed, 3)
        result["timestamp"] = time.time()

        self._actions_log.append(result)
        logger.info("Recovery result for %s: recovered=%s", failure_type, result.get("recovered"))
        return result

    def get_action_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent recovery actions."""
        return list(self._actions_log[-limit:])

    def _recover_cache_full(self, context: dict[str, Any]) -> dict[str, Any]:
        """Clear short-term caches (safe, reversible)."""
        try:
            from memory import ShortTermCache
            cache = ShortTermCache()
            cache.clear()
            return {"recovered": True, "action": "cleared_short_term_cache"}
        except Exception as exc:
            return {"recovered": False, "action": "clear_cache_failed", "error": str(exc)}

    def _recover_engine_cache(self, context: dict[str, Any]) -> dict[str, Any]:
        """Clear engine instance cache (safe — instances will be recreated on demand)."""
        try:
            from engines.registry import clear_cache
            clear_cache()
            return {"recovered": True, "action": "cleared_engine_cache"}
        except Exception as exc:
            return {"recovered": False, "action": "clear_engine_cache_failed", "error": str(exc)}

    def _recover_high_error_rate(self, context: dict[str, Any]) -> dict[str, Any]:
        """Response to high error rate — log recommendation, do not modify code."""
        engine = context.get("engine_name", "unknown")
        error_rate = context.get("error_rate", 0)
        return {
            "recovered": False,
            "action": "recommendation_only",
            "recommendation": f"Engine '{engine}' has {error_rate:.0%} error rate. "
                              f"Manual investigation required — check prompts and model responses.",
        }

    def _recover_memory_pressure(self, context: dict[str, Any]) -> dict[str, Any]:
        """Reduce memory usage by clearing non-essential caches."""
        actions = []
        try:
            from memory import ShortTermCache
            ShortTermCache().clear()
            actions.append("cleared_short_term_cache")
        except Exception:
            pass

        try:
            from engines.registry import clear_cache
            clear_cache()
            actions.append("cleared_engine_cache")
        except Exception:
            pass

        return {
            "recovered": len(actions) > 0,
            "action": "cleared_caches",
            "details": actions,
        }
