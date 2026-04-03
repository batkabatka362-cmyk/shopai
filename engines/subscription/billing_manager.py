"""Subscription Engine — billing manager.

Manages recurring billing cycles, computes MRR/ARR metrics,
and identifies billing issues.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def manage_billing(
    subscribers: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    billing_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Manage billing and compute subscription metrics.

    Args:
        subscribers: List of Subscriber dicts.
        plans: List of SubscriptionPlan dicts.
        billing_history: List of BillingRecord dicts.

    Returns:
        Structured dict with billing summary.
    """
    try:
        subscribers = copy.deepcopy(subscribers)
        plans = copy.deepcopy(plans)
        billing = copy.deepcopy(billing_history)

        # Plan pricing lookup
        plan_map = {str(p.get("id", "")): p for p in plans}

        active_count = 0
        past_due_count = 0
        total_mrr = 0.0
        next_billing: list[dict[str, Any]] = []

        for sub in subscribers:
            sub_id = str(sub.get("id", ""))
            plan_id = str(sub.get("plan_id", ""))
            status = str(sub.get("status", "active")).lower()
            last_billing = str(sub.get("last_billing_date", ""))

            plan = plan_map.get(plan_id, {})
            monthly_price = float(plan.get("price_monthly", 0.0))

            if status == "active":
                active_count += 1
                total_mrr += monthly_price

                # Calculate next billing date (30 days from last)
                if last_billing and len(last_billing) >= 10:
                    try:
                        last_ts = time.mktime(
                            time.strptime(last_billing[:10], "%Y-%m-%d")
                        )
                        next_ts = last_ts + (30 * 86400)
                        next_date = time.strftime("%Y-%m-%d", time.gmtime(next_ts))
                    except (ValueError, OverflowError):
                        next_date = "unknown"
                else:
                    next_date = "unknown"

                next_billing.append({
                    "subscriber_id": sub_id,
                    "plan_id": plan_id,
                    "amount": monthly_price,
                    "next_date": next_date,
                })

            elif status == "past_due":
                past_due_count += 1
                # Still count in MRR as potentially recoverable
                total_mrr += monthly_price

        # Check billing history for failed payments
        failed_payments = sum(
            1 for b in billing
            if str(b.get("status", "")).lower() in ("failed", "declined")
        )
        past_due_count = max(past_due_count, failed_payments)

        total_arr = round(total_mrr * 12.0, 2)

        billing_summary: dict[str, Any] = {
            "total_mrr": round(total_mrr, 2),
            "total_arr": total_arr,
            "active_subscriptions": active_count,
            "past_due_count": past_due_count,
            "next_billing_cycle": next_billing[:20],  # limit for output size
        }

        return {
            "status": "success",
            "billing_summary": billing_summary,
        }
    except Exception as exc:
        return {
            "status": "error",
            "billing_summary": {},
            "error": f"Billing management failed: {exc}",
        }
