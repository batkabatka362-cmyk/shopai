"""Autonomous Control Engine — resource monitor.

Monitors system resource usage against the allocated budget.
"""
from __future__ import annotations

import copy
from typing import Any


def monitor_resources(
    actions: list[dict[str, Any]],
    resource_budget: dict[str, Any],
) -> dict[str, Any]:
    """Estimate resource usage for the given actions and check budget.

    Args:
        actions: List of ActionItem dicts.
        resource_budget: ResourceBudget dict.

    Returns:
        Structured dict with resource usage estimate.
    """
    try:
        items = copy.deepcopy(actions)
        max_cpu = float(resource_budget.get("max_cpu_pct", 100.0))
        max_memory = int(resource_budget.get("max_memory_mb", 4096))
        max_api_calls = int(resource_budget.get("max_api_calls", 1000))
        max_cost = float(resource_budget.get("max_cost_usd", 100.0))

        estimated_cpu = min(len(items) * 2.5, 100.0)
        estimated_memory = len(items) * 50
        estimated_api_calls = sum(1 + len(a.get("params", {})) for a in items)
        estimated_cost = round(estimated_api_calls * 0.01, 2)

        within_budget = (
            estimated_cpu <= max_cpu
            and estimated_memory <= max_memory
            and estimated_api_calls <= max_api_calls
            and estimated_cost <= max_cost
        )

        return {
            "status": "success",
            "usage": {
                "cpu_pct": round(estimated_cpu, 1),
                "memory_mb": estimated_memory,
                "api_calls_used": estimated_api_calls,
                "cost_usd": estimated_cost,
                "within_budget": within_budget,
            },
        }
    except Exception as exc:
        return {"status": "error", "usage": {}, "error": f"Resource monitoring failed: {exc}"}
