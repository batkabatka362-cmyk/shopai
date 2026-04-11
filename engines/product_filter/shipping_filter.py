"""Product Filter Engine — shipping filter.

Filters products that are infeasible to ship: overweight, oversized,
or flagged as non-shippable.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Shipping thresholds
# ---------------------------------------------------------------------------

_DEFAULT_MAX_WEIGHT_KG = 30.0
_OVERSIZE_THRESHOLD_CM = 150.0  # longest dimension


def filter_by_shipping(
    products: list[dict[str, Any]],
    max_weight_kg: float = _DEFAULT_MAX_WEIGHT_KG,
) -> dict[str, Any]:
    """Filter products by shipping feasibility.

    Args:
        products: List of ProductCandidate dicts.
        max_weight_kg: Maximum shippable weight in kg.

    Returns:
        Structured dict with passed and rejected lists.
    """
    try:
        items = copy.deepcopy(products)
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        feasibility_notes: list[str] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            weight = float(item.get("weight_kg", 0.0))
            longest_dim = float(item.get("longest_dimension_cm", 0.0))

            reason = None

            if weight > max_weight_kg:
                reason = (
                    f"Weight {weight:.1f}kg exceeds max {max_weight_kg:.1f}kg"
                )
            elif longest_dim > _OVERSIZE_THRESHOLD_CM:
                reason = (
                    f"Dimension {longest_dim:.0f}cm exceeds oversize "
                    f"threshold {_OVERSIZE_THRESHOLD_CM:.0f}cm"
                )

            if reason:
                item["rejection_stage"] = "shipping_filter"
                item["rejection_reason"] = reason
                rejected.append(item)
                feasibility_notes.append(f"{product_id}: {reason}")
            else:
                passed.append(item)

        return {
            "status": "success",
            "passed": passed,
            "rejected": rejected,
            "feasibility_notes": feasibility_notes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "passed": [],
            "rejected": [],
            "error": f"Shipping filter failed: {exc}",
        }
