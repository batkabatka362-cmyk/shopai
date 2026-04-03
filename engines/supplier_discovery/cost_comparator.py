"""Supplier Discovery Engine — cost comparator.

Compare costs across qualified suppliers.
"""
from __future__ import annotations

import copy
from typing import Any


def compare_costs(
    **kwargs: Any,
) -> dict[str, Any]:
    """Compare costs across suppliers.

    Args:
        **kwargs: Must include qualification results and budget.

    Returns:
        Structured dict with cost comparison.
    """
    try:
        qual_data = kwargs.get("qualification_checker_data", {})
        qualified = copy.deepcopy(qual_data.get("qualified", []))
        budget = kwargs.get("budget", {})
        max_cost = float(budget.get("max_unit_cost", float("inf")))

        comparisons: list[dict[str, Any]] = []

        for sup in qualified:
            unit_cost = float(sup.get("unit_cost", 0))
            moq = int(sup.get("moq", 1))
            total_cost = round(unit_cost * moq, 2)
            within_budget = unit_cost <= max_cost

            comparisons.append({
                "supplier": sup.get("name", "unknown"),
                "unit_cost": unit_cost,
                "moq": moq,
                "total_min_order_cost": total_cost,
                "within_budget": within_budget,
            })

        comparisons.sort(key=lambda c: c["unit_cost"])

        return {
            "status": "success",
            "result": {
                "comparison": comparisons,
                "cheapest": comparisons[0] if comparisons else None,
                "within_budget_count": sum(1 for c in comparisons if c["within_budget"]),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Cost comparison failed: {exc}"}
