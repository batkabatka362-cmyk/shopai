"""Data-First Middleware — auto read/write data on every operation.

RULE: No operation runs without data. No operation completes without recording.

Before every action:
  1. Check memory for relevant past experience
  2. Check data architecture for context
  3. Check rules that apply

After every action:
  1. Record result in DataArchitecture
  2. Record in MemoryIntelligence
  3. Update scores
  4. Check for pattern promotion
"""
from __future__ import annotations
import time
from typing import Any, Callable
from utils.logger import get_logger
logger = get_logger("middleware.data_first")


class DataFirstMiddleware:
    """Wraps any operation with automatic data read/write."""

    def __init__(self) -> None:
        self._mi = None
        self._da = None
        self._operations: int = 0

    def _ensure(self):
        if not self._mi:
            try:
                from core.memory.intelligence import get_memory_intelligence
                self._mi = get_memory_intelligence()
            except Exception as exc:
                logger.debug("DataMiddleware: memory_intelligence init failed: %s", exc)
        if not self._da:
            try:
                from core.data.architecture import get_data_architecture
                self._da = get_data_architecture()
            except Exception as exc:
                logger.debug("DataMiddleware: data_architecture init failed: %s", exc)

    def wrap(self, category: str, action: str,
             func: Callable, *args, **kwargs) -> dict[str, Any]:
        """Wrap any function with data-first pattern.

        Usage:
            middleware.wrap("pricing", "update_price", my_func, arg1, arg2)
        """
        self._ensure()
        start = time.monotonic()

        # BEFORE: read context
        context = self._before(category)

        # EXECUTE
        try:
            result = func(*args, **kwargs)
            success = True
            error = None
        except Exception as exc:
            result = None
            success = False
            error = str(exc)[:200]

        elapsed = time.monotonic() - start

        # AFTER: record everything
        score = self._score(result, success, context)
        self._after(category, action, context, result, score, success, error)

        self._operations += 1
        return {
            "result": result,
            "success": success,
            "error": error,
            "score": score,
            "context_used": context.get("total_memories", 0) > 0,
            "rules_checked": len(context.get("rules", [])),
            "duration_s": round(elapsed, 3),
        }

    def _before(self, category: str) -> dict[str, Any]:
        """Read relevant data before operation."""
        context = {"total_memories": 0, "rules": [], "patterns": []}
        if self._mi:
            try:
                ctx = self._mi.retrieve_for_decision(category)
                context.update(ctx)
            except Exception as exc:
                logger.debug("DataMiddleware._before failed: %s", exc)
        return context

    def _after(self, category: str, action: str, context: dict,
               result: Any, score: float, success: bool, error: str | None) -> None:
        """Record everything after operation."""
        # Memory
        if self._mi:
            try:
                self._mi.create_from_decision(
                    category=category,
                    input_data={"action": action, "context_size": context.get("total_memories", 0)},
                    action=action,
                    result={"success": success, "error": error} if not success else {"success": True},
                    score=score,
                    tags=[category, action, "success" if success else "failure"],
                )
                if not success and error:
                    self._mi.record_failure(
                        category=category,
                        failure_data={"action": action, "error": error},
                        root_cause=error[:50],
                    )
            except Exception as exc:
                logger.debug("DataMiddleware._after memory write failed: %s", exc)

        # Data Architecture
        if self._da:
            try:
                action_id = "mw_{}_{:.0f}".format(action, time.time())
                self._da.record_action(action_id, action, {"category": category})
                self._da.attach_result(action_id, {"success": success}, score=score)
            except Exception as exc:
                logger.debug("DataMiddleware._after DA write failed: %s", exc)

    @staticmethod
    def _score(result: Any, success: bool, context: dict) -> float:
        score = 3.0
        if success:
            score += 1.0
        else:
            score -= 1.5
        if context.get("total_memories", 0) > 0:
            score += 0.3  # Memory-informed = better
        if context.get("rules"):
            score += 0.2
        return max(1.0, min(5.0, score))

    def get_stats(self) -> dict[str, Any]:
        return {"operations": self._operations}


_instance = None
def get_middleware():
    global _instance
    if _instance is None:
        _instance = DataFirstMiddleware()
    return _instance
