"""Referral program analysis — referred customers have 25-50% higher LTV."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_int


def analyze_referral_opportunity(customers: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze referral program opportunity — referred customers have 25-50% higher LTV."""
    if not customers:
        return {"status": "no_data"}

    total = len(customers)
    order_counts = [safe_int(c.get("orders_count", 0)) for c in customers if isinstance(c, dict)]
    repeat_customers = sum(1 for oc in order_counts if oc > 1)
    avg_orders = sum(order_counts) / max(total, 1)

    # Estimate referral program impact
    repeat_pct = repeat_customers / max(total, 1)
    potential_referrers = int(total * repeat_pct)  # Repeat customers are most likely to refer
    expected_referrals = int(potential_referrers * 0.15)  # 15% of repeat customers refer
    referred_ltv_lift = 0.35  # 35% higher LTV for referred customers

    return {
        "total_customers": total,
        "repeat_customers": repeat_customers,
        "potential_referrers": potential_referrers,
        "expected_monthly_referrals": expected_referrals,
        "referred_customer_ltv_lift": f"+{referred_ltv_lift*100:.0f}%",
        "recommended_incentive": {
            "referrer": "$10 store credit per successful referral",
            "referee": "10% off first order",
        },
        "key_insight": "Referred customers convert 4x higher and have 25-50% higher lifetime value. "
                      "A referral program typically costs 5-10% of acquisition cost.",
    }
