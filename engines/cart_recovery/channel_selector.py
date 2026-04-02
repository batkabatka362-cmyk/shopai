"""Cart Recovery Engine — channel selector.

Selects the best communication channel for recovery based on customer
preferences, engagement signals, and strategy type.

Channels:
  - email: default, broadest reach
  - sms: high urgency, returning customers
  - push_notification: mobile-engaged customers
  - retarget_ad: low-engagement / just-browsing customers

Model note: Uses Qwen for analytical channel selection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Channel scoring rules
# ---------------------------------------------------------------------------

# Base channel scores by strategy
_STRATEGY_CHANNEL_SCORES: dict[str, dict[str, float]] = {
    "email_reminder": {
        "email": 0.8,
        "sms": 0.2,
        "push_notification": 0.4,
        "retarget_ad": 0.1,
    },
    "discount_offer": {
        "email": 0.7,
        "sms": 0.4,
        "push_notification": 0.3,
        "retarget_ad": 0.2,
    },
    "free_shipping": {
        "email": 0.7,
        "sms": 0.3,
        "push_notification": 0.3,
        "retarget_ad": 0.1,
    },
    "urgency_message": {
        "email": 0.5,
        "sms": 0.6,
        "push_notification": 0.5,
        "retarget_ad": 0.2,
    },
    "retarget_ad": {
        "email": 0.2,
        "sms": 0.1,
        "push_notification": 0.2,
        "retarget_ad": 0.8,
    },
}

# Fallback channel preferences (ordered)
_FALLBACK_ORDER: list[str] = ["email", "sms", "push_notification", "retarget_ad"]


def select_channel(
    strategy: dict[str, Any],
    customer: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Select the optimal communication channel.

    Args:
        strategy: RecoveryStrategy from strategy selector.
        customer: Customer profile data.
        analysis: CartAnalysis from cart analyzer.

    Returns:
        Structured dict with ChannelSelection data and status.
    """
    try:
        safe_strategy = copy.deepcopy(strategy)
        safe_customer = copy.deepcopy(customer)
        safe_analysis = copy.deepcopy(analysis)

        strategy_name = str(safe_strategy.get("strategy", "email_reminder"))
        customer_type = str(safe_analysis.get("customer_type", "new"))
        total_orders = int(safe_customer.get("total_orders", 0))
        last_purchase_days = int(safe_customer.get("last_purchase_days", 999))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))

        # Start with base scores for this strategy
        base_scores = _STRATEGY_CHANNEL_SCORES.get(
            strategy_name,
            _STRATEGY_CHANNEL_SCORES["email_reminder"],
        )
        scores: dict[str, float] = dict(base_scores)

        # --- Customer type adjustments ---
        if customer_type == "vip":
            scores["email"] += 0.2
            scores["sms"] += 0.1
        elif customer_type == "returning":
            scores["email"] += 0.1
            scores["sms"] += 0.05
        elif customer_type == "new":
            # New customers: prefer less invasive channels
            scores["sms"] -= 0.15
            scores["push_notification"] -= 0.1

        # --- Engagement adjustments ---
        if total_orders >= 3 and last_purchase_days < 30:
            # Recently active — SMS and push are more acceptable
            scores["sms"] += 0.15
            scores["push_notification"] += 0.1
        elif last_purchase_days > 90:
            # Lapsed — retarget might be better
            scores["retarget_ad"] += 0.2
            scores["sms"] -= 0.1

        # --- Cart value adjustments ---
        if cart_value_tier == "high":
            # High value warrants more direct channels
            scores["sms"] += 0.1
            scores["email"] += 0.05
        elif cart_value_tier == "low":
            # Low value doesn't warrant SMS cost
            scores["sms"] -= 0.1
            scores["retarget_ad"] += 0.1

        # --- Select best and fallback ---
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_channel = ranked[0][0]
        fallback_channel = ranked[1][0] if len(ranked) > 1 else "email"

        # Ensure fallback differs from primary
        if fallback_channel == best_channel:
            for ch in _FALLBACK_ORDER:
                if ch != best_channel:
                    fallback_channel = ch
                    break

        rationale = (
            f"Selected '{best_channel}' for '{strategy_name}' strategy "
            f"with {customer_type} customer ({total_orders} orders, "
            f"{last_purchase_days}d since last purchase). "
            f"Fallback: '{fallback_channel}'."
        )

        return {
            "status": "success",
            "channel_selection": {
                "channel": best_channel,
                "fallback_channel": fallback_channel,
                "rationale": rationale,
                "model_note": "Qwen: analytical channel selection based on engagement scoring",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "channel_selection": {},
            "error": f"Channel selection failed: {exc}",
        }
