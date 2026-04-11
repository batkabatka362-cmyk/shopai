"""Subscription Engine — churn predictor.

Predicts subscription churn risk per subscriber based on billing
patterns, tenure, and engagement signals.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def predict_churn(
    subscribers: list[dict[str, Any]],
    billing_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict churn risk for each subscriber.

    Args:
        subscribers: List of Subscriber dicts.
        billing_history: List of BillingRecord dicts.

    Returns:
        Structured dict with per-subscriber churn risks.
    """
    try:
        subscribers = copy.deepcopy(subscribers)
        billing = copy.deepcopy(billing_history)

        # Build per-subscriber billing stats
        sub_billing: dict[str, list[dict[str, Any]]] = {}
        for record in billing:
            sid = str(record.get("subscriber_id", ""))
            if sid:
                sub_billing.setdefault(sid, []).append(record)

        now_ts = time.time()
        churn_risks: list[dict[str, Any]] = []

        for sub in subscribers:
            sid = str(sub.get("id", "unknown"))
            status = str(sub.get("status", "active")).lower()
            join_date = str(sub.get("join_date", ""))
            ltv = float(sub.get("lifetime_value", 0.0))

            if status not in ("active", "past_due"):
                continue

            factors: list[str] = []
            risk_score = 0.0

            # Factor 1: Payment failures
            sub_records = sub_billing.get(sid, [])
            failed = sum(
                1 for r in sub_records
                if str(r.get("status", "")).lower() in ("failed", "declined")
            )
            if failed >= 2:
                factors.append(f"multiple_payment_failures ({failed})")
                risk_score += 0.30
            elif failed == 1:
                factors.append("single_payment_failure")
                risk_score += 0.15

            # Factor 2: Past due status
            if status == "past_due":
                factors.append("account_past_due")
                risk_score += 0.25

            # Factor 3: Short tenure (< 3 months)
            if join_date and len(join_date) >= 10:
                try:
                    join_ts = time.mktime(
                        time.strptime(join_date[:10], "%Y-%m-%d")
                    )
                    tenure_days = (now_ts - join_ts) / 86400.0
                    if tenure_days < 90:
                        factors.append("short_tenure")
                        risk_score += 0.20
                    elif tenure_days < 180:
                        factors.append("moderate_tenure")
                        risk_score += 0.05
                except (ValueError, OverflowError):
                    pass

            # Factor 4: Low lifetime value
            if ltv > 0 and ltv < 50.0:
                factors.append("low_lifetime_value")
                risk_score += 0.10

            # Factor 5: Downgrade pattern (decreasing payment amounts)
            if len(sub_records) >= 3:
                amounts = [
                    float(r.get("amount", 0.0))
                    for r in sorted(sub_records, key=lambda r: r.get("date", ""))
                ]
                if len(amounts) >= 3 and amounts[-1] < amounts[0] * 0.8:
                    factors.append("downgrade_pattern")
                    risk_score += 0.15

            risk_score = round(min(risk_score, 1.0), 2)

            # Risk level classification
            if risk_score >= 0.6:
                risk_level = "high"
                action = "immediate_retention_outreach"
            elif risk_score >= 0.3:
                risk_level = "medium"
                action = "proactive_engagement"
            elif risk_score > 0:
                risk_level = "low"
                action = "monitor"
            else:
                risk_level = "minimal"
                action = "none"

            if factors:  # only include subscribers with some risk
                churn_risks.append({
                    "subscriber_id": sid,
                    "risk": risk_score,
                    "risk_level": risk_level,
                    "churn_factors": factors,
                    "recommended_action": action,
                })

        # Sort by risk descending
        churn_risks.sort(key=lambda x: x["risk"], reverse=True)

        return {
            "status": "success",
            "churn_risks": churn_risks,
        }
    except Exception as exc:
        return {
            "status": "error",
            "churn_risks": [],
            "error": f"Churn prediction failed: {exc}",
        }
