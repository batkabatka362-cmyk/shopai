"""Cart Recovery Engine — value estimator.

Estimates the probability of successful recovery and expected revenue
based on all upstream pipeline outputs.

Model note: no model usage — deterministic probability estimation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Base recovery rates by strategy (industry benchmarks)
# ---------------------------------------------------------------------------

_BASE_RECOVERY_RATES: dict[str, float] = {
    "email_reminder": 0.10,
    "discount_offer": 0.18,
    "free_shipping": 0.20,
    "urgency_message": 0.12,
    "retarget_ad": 0.05,
}

# Confidence base per strategy (how reliable is this estimate)
_BASE_CONFIDENCE: dict[str, float] = {
    "email_reminder": 0.60,
    "discount_offer": 0.65,
    "free_shipping": 0.70,
    "urgency_message": 0.55,
    "retarget_ad": 0.40,
}


def estimate_value(
    analysis: dict[str, Any],
    classification: dict[str, Any],
    strategy: dict[str, Any],
    incentive: dict[str, Any],
    channel_selection: dict[str, Any],
) -> dict[str, Any]:
    """Estimate recovery probability and expected revenue.

    Args:
        analysis: CartAnalysis from cart analyzer.
        classification: AbandonmentClassification from classifier.
        strategy: RecoveryStrategy from strategy selector.
        incentive: Incentive from incentive calculator.
        channel_selection: ChannelSelection from channel selector.

    Returns:
        Structured dict with ValueEstimate data and status.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_classification = copy.deepcopy(classification)
        safe_strategy = copy.deepcopy(strategy)
        safe_incentive = copy.deepcopy(incentive)
        safe_channel = copy.deepcopy(channel_selection)

        strategy_name = str(safe_strategy.get("strategy", "email_reminder"))
        total_value = float(safe_analysis.get("total_value", 0))
        customer_type = str(safe_analysis.get("customer_type", "new"))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))
        hours_since = float(safe_analysis.get("hours_since_abandonment", 0))
        classification_confidence = float(safe_classification.get("confidence", 0))
        reason = str(safe_classification.get("reason", "distraction"))
        incentive_type = str(safe_incentive.get("type", "none"))
        incentive_value = float(safe_incentive.get("value", 0))
        channel = str(safe_channel.get("channel", "email"))

        # --- Base recovery probability ---
        base_prob = _BASE_RECOVERY_RATES.get(strategy_name, 0.10)
        factors: list[str] = [f"base_rate_{strategy_name}={base_prob:.2f}"]

        # --- Customer type modifier ---
        if customer_type == "vip":
            base_prob *= 1.4
            factors.append("vip_customer_boost_+40%")
        elif customer_type == "returning":
            base_prob *= 1.2
            factors.append("returning_customer_boost_+20%")
        else:
            factors.append("new_customer_no_modifier")

        # --- Time decay ---
        if hours_since < 2:
            base_prob *= 1.2
            factors.append("recent_abandonment_boost_+20%")
        elif hours_since > 48:
            base_prob *= 0.6
            factors.append("stale_cart_penalty_-40%")
        elif hours_since > 24:
            base_prob *= 0.8
            factors.append("day_old_cart_penalty_-20%")

        # --- Incentive boost ---
        if incentive_type == "percentage" and incentive_value > 0:
            boost = min(incentive_value / 100.0 * 0.5, 0.10)
            base_prob += boost
            factors.append(f"discount_{incentive_value}%_boost_+{boost:.2f}")
        elif incentive_type == "free_shipping":
            base_prob += 0.08
            factors.append("free_shipping_boost_+0.08")
        elif incentive_type == "loyalty_points":
            base_prob += 0.03
            factors.append("loyalty_points_boost_+0.03")

        # --- Channel effectiveness ---
        if channel == "email":
            factors.append("email_channel_standard")
        elif channel == "sms":
            base_prob *= 1.15
            factors.append("sms_channel_boost_+15%")
        elif channel == "push_notification":
            base_prob *= 1.05
            factors.append("push_channel_minor_boost_+5%")
        elif channel == "retarget_ad":
            base_prob *= 0.7
            factors.append("retarget_ad_lower_conversion_-30%")

        # --- Abandonment reason modifier ---
        if reason == "distraction":
            base_prob *= 1.3
            factors.append("distraction_high_recovery_potential_+30%")
        elif reason == "just_browsing":
            base_prob *= 0.5
            factors.append("just_browsing_low_intent_-50%")
        elif reason == "payment_issue":
            base_prob *= 0.9
            factors.append("payment_issue_moderate_-10%")

        # Clamp probability
        recovery_probability = round(min(max(base_prob, 0.01), 0.85), 4)

        # --- Expected revenue ---
        # Revenue = probability * (cart total - discount amount)
        discount_amount = 0.0
        if incentive_type == "percentage" and incentive_value > 0:
            discount_amount = total_value * (incentive_value / 100.0)
        net_value = max(total_value - discount_amount, 0.0)
        expected_revenue = round(recovery_probability * net_value, 2)

        # --- Confidence ---
        base_conf = _BASE_CONFIDENCE.get(strategy_name, 0.50)
        # Adjust confidence based on classification confidence
        confidence = round(base_conf * (0.5 + classification_confidence * 0.5), 4)
        confidence = min(max(confidence, 0.05), 0.95)

        return {
            "status": "success",
            "estimate": {
                "recovery_probability": recovery_probability,
                "expected_revenue": expected_revenue,
                "confidence": confidence,
                "factors": factors,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimate": {},
            "error": f"Value estimation failed: {exc}",
        }
