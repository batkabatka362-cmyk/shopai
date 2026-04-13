"""ToolOrchestrator — intelligent action routing with scoring, fallback, and self-improvement.

The orchestrator sits between callers (engines, the execution bridge, etc.)
and the tool adapters.  For each requested action it:

1. Discovers which adapters support the action via the registry.
2. Scores each candidate using an exponential-moving-average (EMA) of past
   success rate, latency, and cost — blended with optional caller preferences.
3. Tries the best-scoring adapter first; on failure, falls back down the ranked
   list (or an explicit fallback chain if one was registered).
4. Records every outcome so future scores automatically improve.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from .base import BaseToolAdapter, HealthStatus, ToolMetadata, ToolResult
from .registry import ToolRegistry


# EMA smoothing factor — higher values weight recent observations more.
_EMA_ALPHA = 0.3

# Default scoring weights
_W_SUCCESS = 0.45
_W_SPEED = 0.25
_W_COST = 0.20
_W_PREFERENCE = 0.10


class ToolOrchestrator:
    """Routes actions to the best available tool adapter with automatic fallback.

    Parameters
    ----------
    registry:
        The :class:`ToolRegistry` that holds all registered adapters.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

        # Explicit fallback chains: action -> ordered list of tool_names
        self._fallback_chains: dict[str, list[str]] = {}

        # Performance database: tool_name:action -> _ToolStats
        self._performance_db: dict[str, _ToolStats] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        action: str,
        params: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute *action* using the best available tool.

        Parameters
        ----------
        action:
            The capability name, e.g. ``"product.search"``.
        params:
            Arbitrary parameters forwarded to the adapter.
        preferences:
            Optional hints that influence tool selection.  Recognised keys:

            * ``preferred_tool`` (str) — bonus for this tool name.
            * ``max_cost_usd`` (float) — hard cap; skip tools whose average
              cost exceeds this value.
            * ``timeout_ms`` (float) — overall deadline (not yet enforced
              per-attempt, but available to adapters).
        """
        preferences = preferences or {}
        candidates = self._resolve_candidates(action, preferences)

        if not candidates:
            return ToolResult(
                success=False,
                error=f"No tool supports action '{action}'",
                metadata=ToolMetadata(tool_name="", action=action),
            )

        last_result: ToolResult | None = None
        for adapter in candidates:
            result = self._try_adapter(adapter, action, params)
            self._record_outcome(adapter, action, result)
            if result.success:
                return result
            last_result = result

        # All candidates failed — return the last failure
        return last_result  # type: ignore[return-value]

    def register_fallback_chain(self, action: str, tool_names: list[str]) -> None:
        """Register an explicit ordered fallback chain for *action*.

        When set, the orchestrator tries tools in this exact order instead
        of relying on dynamic scoring.
        """
        with self._lock:
            self._fallback_chains[action] = list(tool_names)

    def get_performance_report(self) -> dict[str, Any]:
        """Return a snapshot of the performance database."""
        with self._lock:
            report: dict[str, Any] = {}
            for key, stats in self._performance_db.items():
                report[key] = {
                    "total_calls": stats.total_calls,
                    "successes": stats.successes,
                    "failures": stats.total_calls - stats.successes,
                    "success_rate_ema": round(stats.success_rate_ema, 4),
                    "avg_latency_ms_ema": round(stats.latency_ema, 2),
                    "avg_cost_usd_ema": round(stats.cost_ema, 6),
                    "last_used": stats.last_used_iso,
                }
            return report

    def health_check_all(self) -> dict[str, HealthStatus]:
        """Delegate to registry-wide health check."""
        return self._registry.health_check_all()

    # ------------------------------------------------------------------
    # Candidate resolution & scoring
    # ------------------------------------------------------------------

    def _resolve_candidates(
        self, action: str, preferences: dict[str, Any]
    ) -> list[BaseToolAdapter]:
        """Build an ordered list of adapters to try for *action*."""

        # If an explicit fallback chain is registered, use it.
        with self._lock:
            chain = self._fallback_chains.get(action)
        if chain:
            ordered: list[BaseToolAdapter] = []
            for name in chain:
                adapter = self._registry.get(name)
                if adapter is not None and action in adapter.capabilities():
                    ordered.append(adapter)
            if ordered:
                return ordered

        # Otherwise score dynamically
        candidates = self._registry.find_by_capability(action)
        if not candidates:
            return []

        max_cost = preferences.get("max_cost_usd")
        if max_cost is not None:
            candidates = [
                c for c in candidates
                if self._get_stats(c, action).cost_ema <= max_cost
            ]

        scored = [
            (self._score_tool(c, action, preferences), c) for c in candidates
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [adapter for _, adapter in scored]

    def _score_tool(
        self,
        tool: BaseToolAdapter,
        action: str,
        preferences: dict[str, Any],
    ) -> float:
        """Compute a composite score in [0, 1] for *tool* on *action*.

        score = w_success * success_rate_ema
              + w_speed  * speed_factor
              + w_cost   * cost_factor
              + w_pref   * preference_bonus

        ``speed_factor`` = 1 / (1 + latency_ema / 1000)  → fast tools ~1, slow ~0
        ``cost_factor``  = 1 / (1 + cost_ema * 100)       → cheap tools ~1
        ``preference_bonus`` = 1.0 if tool matches preferred_tool, else 0.0
        """
        stats = self._get_stats(tool, action)

        success_rate = stats.success_rate_ema
        speed_factor = 1.0 / (1.0 + stats.latency_ema / 1000.0)
        cost_factor = 1.0 / (1.0 + stats.cost_ema * 100.0)

        preferred = preferences.get("preferred_tool", "")
        pref_bonus = 1.0 if tool.tool_name == preferred else 0.0

        score = (
            _W_SUCCESS * success_rate
            + _W_SPEED * speed_factor
            + _W_COST * cost_factor
            + _W_PREFERENCE * pref_bonus
        )
        return score

    # ------------------------------------------------------------------
    # Execution & recording
    # ------------------------------------------------------------------

    def _try_adapter(
        self,
        adapter: BaseToolAdapter,
        action: str,
        params: dict[str, Any],
    ) -> ToolResult:
        """Execute a single adapter and time it."""
        start = time.monotonic()
        try:
            result = adapter.execute(action, params)
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            result = ToolResult(
                success=False,
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=round(duration_ms, 2),
                    tool_name=adapter.tool_name,
                    action=action,
                ),
            )
        else:
            duration_ms = (time.monotonic() - start) * 1000
            if result.metadata is None:
                result.metadata = ToolMetadata(
                    duration_ms=round(duration_ms, 2),
                    tool_name=adapter.tool_name,
                    action=action,
                )
            else:
                result.metadata.duration_ms = round(duration_ms, 2)
                result.metadata.tool_name = adapter.tool_name
                result.metadata.action = action
        return result

    def _record_outcome(
        self, adapter: BaseToolAdapter, action: str, result: ToolResult
    ) -> None:
        """Update the EMA-based performance stats for this tool+action."""
        stats = self._get_stats(adapter, action)
        duration = result.metadata.duration_ms if result.metadata else 0.0
        cost = result.metadata.cost_usd if result.metadata else 0.0

        with self._lock:
            stats.total_calls += 1
            if result.success:
                stats.successes += 1

            # Exponential moving averages
            success_val = 1.0 if result.success else 0.0
            stats.success_rate_ema = (
                _EMA_ALPHA * success_val + (1 - _EMA_ALPHA) * stats.success_rate_ema
            )
            stats.latency_ema = (
                _EMA_ALPHA * duration + (1 - _EMA_ALPHA) * stats.latency_ema
            )
            stats.cost_ema = (
                _EMA_ALPHA * cost + (1 - _EMA_ALPHA) * stats.cost_ema
            )
            stats.last_used_iso = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )

    def _get_stats(self, tool: BaseToolAdapter, action: str) -> _ToolStats:
        """Retrieve or initialise stats for *tool*:*action*."""
        key = f"{tool.tool_name}:{action}"
        with self._lock:
            if key not in self._performance_db:
                self._performance_db[key] = _ToolStats()
            return self._performance_db[key]


# ------------------------------------------------------------------
# Internal stats container
# ------------------------------------------------------------------


class _ToolStats:
    """Mutable EMA-tracked statistics for one tool+action pair."""

    __slots__ = (
        "total_calls",
        "successes",
        "success_rate_ema",
        "latency_ema",
        "cost_ema",
        "last_used_iso",
    )

    def __init__(self) -> None:
        self.total_calls: int = 0
        self.successes: int = 0
        # Start optimistic so new tools get a fair chance
        self.success_rate_ema: float = 0.5
        self.latency_ema: float = 500.0  # assume 500ms until proven otherwise
        self.cost_ema: float = 0.0
        self.last_used_iso: str = ""
