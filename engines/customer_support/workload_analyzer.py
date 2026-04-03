"""Customer Support Engine — workload analyzer.

Analyze support team workload distribution and capacity.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_workload(
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze support team workload.

    Args:
        **kwargs: Must include 'agents' list and ticket data.

    Returns:
        Structured dict with workload analysis.
    """
    try:
        agents = copy.deepcopy(kwargs.get("agents", []))
        tickets = kwargs.get("tickets", [])
        class_data = kwargs.get("ticket_classifier_data", {})
        classified = class_data.get("classified_tickets", [])

        total_tickets = len(classified)
        total_agents = len(agents)
        avg_per_agent = round(total_tickets / max(total_agents, 1), 1)

        # Category distribution
        category_counts: dict[str, int] = {}
        priority_counts: dict[str, int] = {}
        for t in classified:
            cat = t.get("category", "general")
            pri = t.get("priority", "low")
            category_counts[cat] = category_counts.get(cat, 0) + 1
            priority_counts[pri] = priority_counts.get(pri, 0) + 1

        # Agent utilization
        agent_stats: list[dict[str, Any]] = []
        for agent in agents:
            capacity = int(agent.get("max_tickets_per_day", 20))
            current = int(agent.get("current_tickets", 0))
            utilization = round(current / max(capacity, 1) * 100, 1)
            agent_stats.append({
                "agent_id": str(agent.get("id", "")),
                "name": agent.get("name", ""),
                "current_tickets": current,
                "capacity": capacity,
                "utilization_pct": utilization,
                "overloaded": utilization > 100,
            })

        overloaded = sum(1 for a in agent_stats if a["overloaded"])

        return {
            "status": "success",
            "result": {
                "workload_report": {
                    "total_tickets": total_tickets,
                    "total_agents": total_agents,
                    "avg_per_agent": avg_per_agent,
                    "category_distribution": category_counts,
                    "priority_distribution": priority_counts,
                    "overloaded_agents": overloaded,
                    "agent_stats": agent_stats,
                },
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Workload analysis failed: {exc}"}
