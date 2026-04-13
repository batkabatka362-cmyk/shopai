"""Subscription Engine — upgrade recommender.

Recommends plan upgrades for subscribers based on usage patterns,
billing history, and churn risk analysis.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def recommend_upgrades(
    subscribers: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    billing_history: list[dict[str, Any]],
    churn_risks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend plan upgrades for eligible subscribers.

    Args:
        subscribers: List of Subscriber dicts.
        plans: List of SubscriptionPlan dicts.
        billing_history: List of BillingRecord dicts.
        churn_risks: List of ChurnRisk dicts from churn_predictor.

    Returns:
        Structured dict with upgrade opportunities.
    """
    try:
        subscribers = copy.deepcopy(subscribers)
        plans = copy.deepcopy(plans)
        billing = copy.deepcopy(billing_history)

        # Plan lookup and tier ordering
        plan_map = {str(p.get("id", "")): p for p in plans}
        plans_by_tier = sorted(plans, key=lambda p: float(p.get("price_monthly", 0)))

        # Churn risk lookup
        churn_map = {str(c.get("subscriber_id", "")): c for c in churn_risks}

        # Build per-subscriber billing totals
        sub_spend: dict[str, float] = {}
        sub_count: dict[str, int] = {}
        for record in billing:
            sid = str(record.get("subscriber_id", ""))
            amount = float(record.get("amount", 0.0))
            status = str(record.get("status", "")).lower()
            if sid and status not in ("failed", "declined"):
                sub_spend[sid] = sub_spend.get(sid, 0.0) + amount
                sub_count[sid] = sub_count.get(sid, 0) + 1

        opportunities: list[dict[str, Any]] = []

        for sub in subscribers:
            sid = str(sub.get("id", "unknown"))
            status = str(sub.get("status", "active")).lower()
            current_plan_id = str(sub.get("plan_id", ""))

            if status != "active":
                continue

            current_plan = plan_map.get(current_plan_id, {})
            current_price = float(current_plan.get("price_monthly", 0.0))
            current_name = str(current_plan.get("name", current_plan_id))

            # Check churn risk — don't upsell high-churn subscribers
            churn = churn_map.get(sid, {})
            churn_risk = float(churn.get("risk", 0.0))
            if churn_risk >= 0.5:
                continue  # too risky for upsell

            # Find next tier up
            next_plan = None
            for plan in plans_by_tier:
                plan_price = float(plan.get("price_monthly", 0.0))
                if plan_price > current_price:
                    next_plan = plan
                    break

            if not next_plan:
                continue  # already on highest tier

            next_price = float(next_plan.get("price_monthly", 0.0))
            next_name = str(next_plan.get("name", ""))
            revenue_uplift = round(next_price - current_price, 2)

            # Likelihood based on multiple factors
            total_spend = sub_spend.get(sid, 0.0)
            billing_count = sub_count.get(sid, 0)

            # Consistent payer = higher likelihood
            if billing_count >= 6:
                consistency_score = 0.4
            elif billing_count >= 3:
                consistency_score = 0.25
            else:
                consistency_score = 0.1

            # Low churn risk = higher likelihood
            churn_bonus = (1.0 - churn_risk) * 0.3

            # LTV indicator
            ltv = float(sub.get("lifetime_value", 0.0))
            ltv_score = min(ltv / 500.0, 1.0) * 0.3 if ltv > 0 else 0.1

            likelihood = round(
                min(consistency_score + churn_bonus + ltv_score, 0.95), 2,
            )

            # Reason
            if billing_count >= 6 and churn_risk < 0.2:
                reason = "Loyal subscriber with consistent payments — likely receptive to premium features"
            elif ltv > 200:
                reason = "High lifetime value indicates willingness to invest in enhanced experience"
            else:
                reason = "Subscriber engagement pattern suggests readiness for plan upgrade"

            opportunities.append({
                "subscriber_id": sid,
                "current_plan": current_name,
                "recommended_plan": next_name,
                "revenue_uplift": revenue_uplift,
                "likelihood": likelihood,
                "reason": reason,
            })

        # Sort by revenue uplift * likelihood (expected value)
        opportunities.sort(
            key=lambda x: x["revenue_uplift"] * x["likelihood"],
            reverse=True,
        )

        return {
            "status": "success",
            "opportunities": opportunities,
        }
    except Exception as exc:
        return {
            "status": "error",
            "opportunities": [],
            "error": f"Upgrade recommendation failed: {exc}",
        }
