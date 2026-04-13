"""Selection Decision Engine — constraint checker.

Checks each product against selection constraints (budget, risk
thresholds, category limits, etc.) and reports violations.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_OPERATORS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "in": lambda a, b: a in b if isinstance(b, (list, tuple)) else False,
}


def check_constraints(
    ranked_products: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check products against constraints.

    Args:
        ranked_products: List of ranked product dicts.
        constraints: List of constraint dicts.

    Returns:
        Structured dict with per-product constraint check results.
    """
    try:
        results: list[dict[str, Any]] = []

        for item in ranked_products:
            pid = str(item.get("id", "unknown"))
            violations: list[str] = []

            for constraint in constraints:
                field = str(constraint.get("field", ""))
                operator = str(constraint.get("operator", ""))
                threshold = constraint.get("value")
                description = str(constraint.get("description", f"{field} {operator} {threshold}"))

                product_value = item.get(field)
                if product_value is None:
                    continue

                op_fn = _OPERATORS.get(operator)
                if op_fn is None:
                    continue

                try:
                    if not op_fn(float(product_value) if isinstance(threshold, (int, float)) else product_value, threshold):
                        violations.append(description)
                except (TypeError, ValueError):
                    violations.append(f"Could not evaluate: {description}")

            results.append({
                "product_id": pid,
                "passes_all": len(violations) == 0,
                "violations": violations,
                "violation_count": len(violations),
            })

        return {"status": "success", "checks": results}
    except Exception as exc:
        return {"status": "error", "checks": [], "error": f"Constraint checking failed: {exc}"}
