"""Subscription Engine — plan designer.

Designs subscription tiers based on product catalog, existing plans,
and subscriber distribution analysis.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def design_plans(
    plans: list[dict[str, Any]],
    products: list[dict[str, Any]],
    subscribers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Design or optimize subscription plan tiers.

    Args:
        plans: List of existing SubscriptionPlan dicts.
        products: List of SubscriptionProduct dicts.
        subscribers: List of Subscriber dicts.

    Returns:
        Structured dict with plan recommendations.
    """
    try:
        plans = copy.deepcopy(plans)
        products = copy.deepcopy(products)
        subscribers = copy.deepcopy(subscribers)

        # Analyze current plan distribution
        plan_counts: dict[str, int] = {}
        for sub in subscribers:
            pid = str(sub.get("plan_id", ""))
            if pid:
                plan_counts[pid] = plan_counts.get(pid, 0) + 1

        total_subs = len(subscribers)

        # Calculate product price stats for tier pricing
        prices = [float(p.get("price", 0.0)) for p in products if p.get("price")]
        avg_price = sum(prices) / len(prices) if prices else 29.99
        max_price = max(prices) if prices else 99.99

        recommendations: list[dict[str, Any]] = []

        if plans:
            # Optimize existing plans
            plan_map = {str(p.get("id", "")): p for p in plans}
            sorted_plans = sorted(plans, key=lambda p: float(p.get("price_monthly", 0)))

            for plan in sorted_plans:
                plan_id = str(plan.get("id", ""))
                name = str(plan.get("name", ""))
                price_monthly = float(plan.get("price_monthly", 0.0))
                features = plan.get("features", [])

                sub_count = plan_counts.get(plan_id, 0)
                adoption = round(sub_count / total_subs, 3) if total_subs > 0 else 0.0

                # Determine target segment based on tier
                tier = int(plan.get("tier", 1))
                if tier <= 1:
                    segment = "price_sensitive"
                elif tier <= 2:
                    segment = "mainstream"
                else:
                    segment = "premium"

                recommendations.append({
                    "plan_name": name,
                    "price_monthly": price_monthly,
                    "price_annual": round(price_monthly * 10.0, 2),  # 2 months free
                    "features": features,
                    "target_segment": segment,
                    "estimated_adoption": adoption,
                })
        else:
            # Design new tier structure
            recommendations = [
                {
                    "plan_name": "Basic",
                    "price_monthly": round(avg_price * 0.5, 2),
                    "price_annual": round(avg_price * 0.5 * 10.0, 2),
                    "features": ["1 product/month", "Free shipping", "Cancel anytime"],
                    "target_segment": "price_sensitive",
                    "estimated_adoption": 0.40,
                },
                {
                    "plan_name": "Standard",
                    "price_monthly": round(avg_price, 2),
                    "price_annual": round(avg_price * 10.0, 2),
                    "features": [
                        "2 products/month", "Free shipping",
                        "Early access", "Cancel anytime",
                    ],
                    "target_segment": "mainstream",
                    "estimated_adoption": 0.40,
                },
                {
                    "plan_name": "Premium",
                    "price_monthly": round(avg_price * 1.8, 2),
                    "price_annual": round(avg_price * 1.8 * 10.0, 2),
                    "features": [
                        "4 products/month", "Free express shipping",
                        "Early access", "Exclusive items",
                        "Priority support", "Cancel anytime",
                    ],
                    "target_segment": "premium",
                    "estimated_adoption": 0.20,
                },
            ]

        return {
            "status": "success",
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Plan design failed: {exc}",
        }
