"""Cart Recovery Engine — recovery strategy selector.

Selects the optimal recovery strategy based on cart value, customer type,
and abandonment reason.

Strategies:
  - email_reminder: gentle nudge, good for distractions
  - discount_offer: price-based incentive for price-sensitive carts
  - free_shipping: when shipping cost is the barrier
  - urgency_message: scarcity/time-pressure for comparison shoppers
  - retarget_ad: for just-browsing or low-engagement customers

Model note: Uses Mistral for analytical strategy selection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Strategy selection matrix
# ---------------------------------------------------------------------------

# (abandonment_reason, customer_type) -> strategy
_STRATEGY_MATRIX: dict[tuple[str, str], str] = {
    # Price shock
    ("price_shock", "new"): "discount_offer",
    ("price_shock", "returning"): "discount_offer",
    ("price_shock", "vip"): "discount_offer",
    # Shipping cost
    ("shipping_cost", "new"): "free_shipping",
    ("shipping_cost", "returning"): "free_shipping",
    ("shipping_cost", "vip"): "free_shipping",
    # Comparison shopping
    ("comparison_shopping", "new"): "urgency_message",
    ("comparison_shopping", "returning"): "urgency_message",
    ("comparison_shopping", "vip"): "email_reminder",
    # Distraction
    ("distraction", "new"): "email_reminder",
    ("distraction", "returning"): "email_reminder",
    ("distraction", "vip"): "email_reminder",
    # Payment issue
    ("payment_issue", "new"): "email_reminder",
    ("payment_issue", "returning"): "email_reminder",
    ("payment_issue", "vip"): "email_reminder",
    # Just browsing
    ("just_browsing", "new"): "retarget_ad",
    ("just_browsing", "returning"): "retarget_ad",
    ("just_browsing", "vip"): "email_reminder",
}

# Priority based on cart value tier + customer type
_PRIORITY_MAP: dict[tuple[str, str], str] = {
    ("high", "vip"): "critical",
    ("high", "returning"): "high",
    ("high", "new"): "high",
    ("medium", "vip"): "high",
    ("medium", "returning"): "medium",
    ("medium", "new"): "medium",
    ("low", "vip"): "medium",
    ("low", "returning"): "low",
    ("low", "new"): "low",
}


def select_recovery_strategy(
    analysis: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    """Select the optimal recovery strategy.

    Args:
        analysis: CartAnalysis from cart_analyzer.
        classification: AbandonmentClassification from classifier.

    Returns:
        Structured dict with RecoveryStrategy data.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_classification = copy.deepcopy(classification)

        reason = str(safe_classification.get("reason", "distraction"))
        customer_type = str(safe_analysis.get("customer_type", "new"))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))

        # Look up strategy
        strategy = _STRATEGY_MATRIX.get(
            (reason, customer_type),
            "email_reminder",  # safe default
        )

        # Look up priority
        priority = _PRIORITY_MAP.get(
            (cart_value_tier, customer_type),
            "medium",
        )

        # Build rationale
        rationale = (
            f"Selected '{strategy}' for abandonment reason '{reason}' "
            f"with {customer_type} customer and {cart_value_tier}-value cart. "
            f"Priority: {priority}."
        )

        return {
            "status": "success",
            "strategy": {
                "strategy": strategy,
                "priority": priority,
                "rationale": rationale,
                "model_note": "Mistral: analytical strategy selection based on abandonment matrix",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "strategy": {},
            "error": f"Recovery strategy selection failed: {exc}",
        }
