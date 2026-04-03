"""Autonomous Control Engine — resource monitor.

Monitors system resource usage against the configured budget.
Tracks CPU, memory, API calls, and cost consumption.
"""
from __future__ import annotations

import copy
from typing import Any


def monitor_resources(
    actions: list[dict[str, Any]],
    resource_budget: dict[str, Any],
) -> dict[str, Any]:
    """Monitor projected resource usage for a batch of actions.

    Args:
        actions: List of ActionItem dicts.
        resource_budget: ResourceBudget configuration.

    Returns:
        Structured dict with resource usage snapshot.
    """
    try:
        items = copy.deepcopy(actions)
        budget = copy.deepcopy(resource_budget)

        max_cpu = float(budget.get("max_cpu_pct", 100.0))
        max_memory = int(budget.get("max_memory_mb", 4096))
        max_api_calls = int(budget.get("max_api_calls", 1000))
        max_cost = float(budget.get("max_cost_usd", 100.0))

        # Estimate resource consumption per action
        total_cpu = 0.0
        total_memory = 0
        total_api_calls = 0
        total_cost = 0.0

        for action in items:
            params = action.get("params", {})
            total_cpu += float(params.get("cpu_estimate_pct", 2.0))
            total_memory += int(params.get("memory_estimate_mb", 50))
            total_api_calls += int(params.get("api_calls_estimate", 1))
            total_cost += float(params.get("estimated_cost", 0.0))

        within_budget = (
            total_cpu <= max_cpu
            and total_memory <= max_memory
            and total_api_calls <= max_api_calls
            and total_cost <= max_cost
        )

        # Headroom: minimum remaining percentage across all resources
        headrooms = []
        if max_cpu > 0:
            headrooms.append((max_cpu - total_cpu) / max_cpu)
        if max_memory > 0:
            headrooms.append((max_memory - total_memory) / max_memory)
        if max_api_calls > 0:
            headrooms.append((max_api_calls - total_api_calls) / max_api_calls)
        if max_cost > 0:
            headrooms.append((max_cost - total_cost) / max_cost)

        headroom_pct = round(min(headrooms) * 100, 1) if headrooms else 0.0

        usage = {
            "cpu_pct": round(total_cpu, 1),
            "memory_mb": total_memory,
            "api_calls_used": total_api_calls,
            "cost_used_usd": round(total_cost, 2),
            "within_budget": within_budget,
            "headroom_pct": max(headroom_pct, 0.0),
        }

        return {
            "status": "success",
            "usage": usage,
        }
    except Exception as exc:
        return {
            "status": "error",
            "usage": {},
            "error": f"Resource monitoring failed: {exc}",
        }
