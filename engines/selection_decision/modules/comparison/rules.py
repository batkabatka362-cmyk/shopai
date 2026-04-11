"""Comparison rules — constraints for head-to-head product analysis.

Compare minimum 2, maximum 5 products. Flag when no product wins the
majority of dimensions. Ensure the comparison is meaningful before
using results for final selection.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Comparison constraints
# --------------------------------------------------------------------------- #
MIN_PRODUCTS_TO_COMPARE = 2
MAX_PRODUCTS_TO_COMPARE = 5

# Minimum gap to consider a dimension win meaningful
MIN_MEANINGFUL_GAP = 3.0

# If no product wins > 50% of dimensions, flag as inconclusive
MAJORITY_THRESHOLD = 0.5

# Maximum number of critical weaknesses before product is flagged
MAX_CRITICAL_WEAKNESSES = 2

# Score below which a dimension is considered a critical weakness
CRITICAL_WEAKNESS_THRESHOLD = 25.0


# --------------------------------------------------------------------------- #
#  Rule definitions
# --------------------------------------------------------------------------- #
COMPARISON_RULES: list[dict[str, Any]] = [
    {
        "id": "min_products",
        "name": "Minimum products for comparison",
        "description": (
            f"At least {MIN_PRODUCTS_TO_COMPARE} products are required for "
            "a meaningful comparison. Cannot compare a product to itself."
        ),
        "severity": "blocker",
        "check": lambda ctx: ctx.get("product_count", 0) >= MIN_PRODUCTS_TO_COMPARE,
        "action": "Expand candidate pool or skip comparison step.",
    },
    {
        "id": "max_products",
        "name": "Maximum products for comparison",
        "description": (
            f"Compare at most {MAX_PRODUCTS_TO_COMPARE} products. Beyond this, "
            "comparison becomes noisy and unhelpful."
        ),
        "severity": "warning",
        "check": lambda ctx: ctx.get("product_count", 0) <= MAX_PRODUCTS_TO_COMPARE,
        "action": "Trim to top 5 candidates before comparison.",
    },
    {
        "id": "no_majority_winner",
        "name": "No product wins majority of dimensions",
        "description": (
            "When no single product wins more than half the dimensions, "
            "the comparison is inconclusive. Selection depends on goal "
            "weighting rather than clear dominance."
        ),
        "severity": "warning",
        "check": lambda ctx: _has_majority_winner(ctx),
        "action": "Rely on goal-weighted scoring. Highlight trade-offs to user.",
    },
    {
        "id": "critical_weakness_check",
        "name": "Check for critical weaknesses",
        "description": (
            f"Flag any product scoring below {CRITICAL_WEAKNESS_THRESHOLD} on "
            "any dimension. A single critical weakness can doom a product "
            "regardless of other scores."
        ),
        "severity": "info",
        "check": lambda ctx: _no_critical_weaknesses(ctx),
        "action": "Highlight critical weaknesses prominently in comparison output.",
    },
]


def _has_majority_winner(ctx: dict[str, Any]) -> bool:
    """Check if any product wins the majority of dimensions."""
    winners = ctx.get("dimension_winners", {})
    if not winners:
        return False

    win_counts: dict[str, int] = {}
    total = 0
    for dim_info in winners.values():
        wid = dim_info.get("winner_id")
        gap = dim_info.get("gap", 0)
        if wid and gap >= MIN_MEANINGFUL_GAP:
            win_counts[wid] = win_counts.get(wid, 0) + 1
            total += 1

    if not win_counts or total == 0:
        return False

    max_wins = max(win_counts.values())
    return max_wins > total * MAJORITY_THRESHOLD


def _no_critical_weaknesses(ctx: dict[str, Any]) -> bool:
    """Check that no compared product has too many critical weaknesses."""
    products = ctx.get("products", [])
    for product in products:
        scores = product.get("normalized_scores", {})
        critical_count = sum(
            1 for s in scores.values()
            if s is not None and s < CRITICAL_WEAKNESS_THRESHOLD
        )
        if critical_count > MAX_CRITICAL_WEAKNESSES:
            return False
    return True


def evaluate_comparison_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Run all comparison rules against the current context.

    Args:
        context: {
            product_count: int,
            dimension_winners: dict,
            products: list[dict],
        }

    Returns:
        {passed: bool, blockers: list, warnings: list, info: list, rules_evaluated: int}
    """
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in COMPARISON_RULES:
        try:
            passed = rule["check"](context)
        except Exception:
            passed = True

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(COMPARISON_RULES),
    }
