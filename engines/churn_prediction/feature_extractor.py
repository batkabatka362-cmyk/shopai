"""Churn Prediction Engine — feature extractor.

Extracts churn-relevant features from raw customer records: days since
last purchase, order frequency, average order value, total lifetime value,
email engagement rate, and support ticket count.

Model note: no model usage — deterministic extraction.
"""
from __future__ import annotations

import copy
from typing import Any


def extract_features(customer: dict[str, Any]) -> dict[str, Any]:
    """Extract churn-relevant features from a raw customer record.

    Args:
        customer: Raw customer record with id, purchase history, engagement data.

    Returns:
        Structured dict with ExtractedFeatures data and status.
    """
    try:
        safe = copy.deepcopy(customer)

        customer_id = str(safe.get("id", "unknown"))
        days_since_last = int(safe.get("days_since_last_purchase", 0))
        total_orders = int(safe.get("total_orders", 0))
        total_spent = float(safe.get("total_spent", 0.0))
        avg_order_value = float(safe.get("avg_order_value", 0.0))
        account_age_days = int(safe.get("account_age_days", 1))
        email_open_rate = float(safe.get("email_open_rate", 0.0))
        support_tickets = int(safe.get("support_tickets_90d", 0))

        # --- Order frequency: orders per 30-day period ---
        if account_age_days > 0:
            order_frequency = round((total_orders / account_age_days) * 30.0, 4)
        else:
            order_frequency = 0.0

        # --- Avg order value: fall back to total_spent / total_orders ---
        if avg_order_value <= 0 and total_orders > 0:
            avg_order_value = round(total_spent / total_orders, 2)

        # --- Lifetime value ---
        total_lifetime_value = round(total_spent, 2)

        # --- Email engagement: clamp to [0, 1] ---
        email_engagement = round(max(0.0, min(1.0, email_open_rate)), 4)

        return {
            "status": "success",
            "features": {
                "customer_id": customer_id,
                "days_since_last": days_since_last,
                "order_frequency": order_frequency,
                "avg_order_value": round(avg_order_value, 2),
                "total_lifetime_value": total_lifetime_value,
                "email_engagement": email_engagement,
                "support_tickets": support_tickets,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "features": {},
            "error": f"Feature extraction failed: {exc}",
        }
