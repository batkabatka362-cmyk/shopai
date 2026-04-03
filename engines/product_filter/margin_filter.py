"""Product Filter Engine — margin filter.

Filters products that fall below the minimum margin threshold.
Products must meet a minimum profit margin percentage to be viable.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def filter_by_margin(
    products: list[dict[str, Any]],
    min_margin_pct: float = 15.0,
) -> dict[str, Any]:
    """Filter products by minimum margin percentage.

    Args:
        products: List of ProductCandidate dicts.
        min_margin_pct: Minimum acceptable margin percentage.

    Returns:
        Structured dict with passed and rejected lists.
    """
    try:
        items = copy.deepcopy(products)
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        rejection_reasons: list[str] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            margin = float(item.get("margin_pct", 0.0))

            # If margin_pct not provided, compute from cost/price
            if margin == 0.0:
                sale_price = float(item.get("sale_price", 0.0))
                unit_cost = float(item.get("unit_cost", 0.0))
                if sale_price > 0:
                    margin = round(((sale_price - unit_cost) / sale_price) * 100.0, 2)
                    item["margin_pct"] = margin

            if margin >= min_margin_pct:
                passed.append(item)
            else:
                item["rejection_stage"] = "margin_filter"
                item["rejection_reason"] = (
                    f"Margin {margin:.1f}% below minimum {min_margin_pct:.1f}%"
                )
                rejected.append(item)
                rejection_reasons.append(
                    f"{product_id}: margin {margin:.1f}% < {min_margin_pct:.1f}%"
                )

        return {
            "status": "success",
            "passed": passed,
            "rejected": rejected,
            "rejection_reasons": rejection_reasons,
        }
    except Exception as exc:
        return {
            "status": "error",
            "passed": [],
            "rejected": [],
            "error": f"Margin filter failed: {exc}",
        }
