"""Customer lifecycle segmentation."""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.customer.lifecycle")

# Customer lifecycle stages
LIFECYCLE_STAGES = {
    "prospect": {
        "description": "Visited but never purchased",
        "goal": "Convert to first purchase",
        "channels": ["retargeting_ads", "email_welcome_series", "social_proof"],
        "kpi": "conversion_rate",
    },
    "first_buyer": {
        "description": "Made 1 purchase",
        "goal": "Convert to repeat buyer",
        "channels": ["post_purchase_email", "product_recommendations", "review_request"],
        "kpi": "repeat_purchase_rate",
    },
    "repeat_buyer": {
        "description": "Made 2-4 purchases",
        "goal": "Build loyalty and increase frequency",
        "channels": ["loyalty_program", "exclusive_offers", "cross_sell"],
        "kpi": "purchase_frequency",
    },
    "loyal": {
        "description": "Made 5+ purchases",
        "goal": "Turn into advocate",
        "channels": ["vip_access", "referral_program", "ambassador_program"],
        "kpi": "referral_rate",
    },
    "at_risk": {
        "description": "No purchase in 60-90 days (was active)",
        "goal": "Re-engage before churn",
        "channels": ["winback_email", "personalized_offer", "feedback_request"],
        "kpi": "reactivation_rate",
    },
    "lapsed": {
        "description": "No purchase in 90+ days",
        "goal": "Last attempt to recover",
        "channels": ["final_offer_email", "survey", "unsubscribe_alternative"],
        "kpi": "recovery_rate",
    },
}


def _top_lifecycle_action(summary: dict[str, Any]) -> str:
    """Determine the single most impactful lifecycle action."""
    at_risk_pct = summary.get("at_risk", {}).get("pct", 0)
    first_buyer_pct = summary.get("first_buyer", {}).get("pct", 0)
    prospect_pct = summary.get("prospect", {}).get("pct", 0)

    if at_risk_pct > 20:
        return f"URGENT: {at_risk_pct}% customers at risk of churn — launch winback campaign immediately"
    if first_buyer_pct > 40:
        return f"{first_buyer_pct}% are one-time buyers — focus on converting to repeat with post-purchase sequence"
    if prospect_pct > 50:
        return f"{prospect_pct}% are prospects — improve first-purchase conversion with welcome series"
    return "Customer lifecycle is balanced — focus on loyalty program expansion"


def segment_by_lifecycle(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Segment customers by lifecycle stage."""
    now = time.time()
    segments: dict[str, list[dict[str, Any]]] = {stage: [] for stage in LIFECYCLE_STAGES}

    for customer in customers:
        if not isinstance(customer, dict):
            continue

        order_count = safe_int(customer.get("orders_count", 0))
        last_order_days = safe_int(customer.get("days_since_last_order", 999))

        # Also check from orders list
        if orders and last_order_days == 999:
            cid = customer.get("id")
            customer_orders = [
                o for o in orders
                if isinstance(o, dict)
                and (o.get("customer_id") == cid or o.get("customer", {}).get("id") == cid)
            ]
            if customer_orders:
                order_count = max(order_count, len(customer_orders))

        name = customer.get("name", customer.get("email", f"Customer {customer.get('id', '?')}"))
        entry = {"name": name, "id": customer.get("id"), "orders": order_count, "days_inactive": last_order_days}

        if order_count == 0:
            segments["prospect"].append(entry)
        elif last_order_days > 90:
            segments["lapsed"].append(entry)
        elif last_order_days > 60:
            segments["at_risk"].append(entry)
        elif order_count >= 5:
            segments["loyal"].append(entry)
        elif order_count >= 2:
            segments["repeat_buyer"].append(entry)
        else:
            segments["first_buyer"].append(entry)

    total = len(customers)
    summary = {}
    for stage, members in segments.items():
        count = len(members)
        info = LIFECYCLE_STAGES[stage]
        summary[stage] = {
            "count": count,
            "pct": round(count / max(total, 1) * 100, 1),
            "goal": info["goal"],
            "recommended_channels": info["channels"],
            "kpi": info["kpi"],
        }

    return {
        "total_customers": total,
        "segments": summary,
        "top_action": _top_lifecycle_action(summary),
    }
