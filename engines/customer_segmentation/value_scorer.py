"""Customer Segmentation Engine — value scorer.

Computes Customer Lifetime Value (CLV) for each customer:
  historical_clv  = actual past revenue
  predicted_future_clv = projected value using purchase frequency, AOV,
                         and expected remaining lifetime
  total_clv = historical + predicted

Uses a simplified BG/NBD-style estimation without external models.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Value tier boundaries (total CLV)
# ---------------------------------------------------------------------------

_TIER_PLATINUM = 5000.0
_TIER_GOLD = 2000.0
_TIER_SILVER = 500.0
_TIER_BRONZE = 100.0


def score_values(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score CLV for all customers.

    Args:
        customers: List of normalized customer dicts.

    Returns:
        Structured dict with list of ValueScore dicts.
    """
    try:
        if not customers:
            return {"status": "success", "scores": [], "count": 0}

        custs = copy.deepcopy(customers)
        scores: list[dict[str, Any]] = []

        for c in custs:
            score = _score_one(c)
            scores.append(score)

        return {
            "status": "success",
            "scores": scores,
            "count": len(scores),
        }
    except Exception as exc:
        return {
            "status": "error",
            "scores": [],
            "count": 0,
            "error": f"Value scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Single-customer CLV
# ---------------------------------------------------------------------------

def _score_one(c: dict[str, Any]) -> dict[str, Any]:
    """Compute CLV for a single customer."""
    cid = c.get("id", "unknown")
    total_spent = float(c.get("total_spent", 0.0))
    total_orders = int(c.get("total_orders", 0))
    aov = float(c.get("avg_order_value", 0.0))
    tenure_days = max(int(c.get("tenure_days", 1)), 1)
    days_since_last = int(c.get("days_since_last", 0))

    # Historical CLV is simply total revenue from this customer
    historical_clv = total_spent

    # Predicted future CLV
    predicted_future_clv = _predict_future_clv(
        total_orders=total_orders,
        aov=aov,
        tenure_days=tenure_days,
        days_since_last=days_since_last,
    )

    total_clv = historical_clv + predicted_future_clv
    value_tier = _assign_tier(total_clv)

    return {
        "customer_id": cid,
        "historical_clv": round(historical_clv, 2),
        "predicted_future_clv": round(predicted_future_clv, 2),
        "total_clv": round(total_clv, 2),
        "value_tier": value_tier,
    }


def _predict_future_clv(
    total_orders: int,
    aov: float,
    tenure_days: int,
    days_since_last: int,
) -> float:
    """Predict future CLV using purchase frequency and recency decay.

    Model: future_clv = purchase_rate * aov * expected_lifetime * alive_probability

    - purchase_rate: orders per year based on observed frequency
    - expected_lifetime: projected remaining active years (capped at 3)
    - alive_probability: exponential decay based on recency gap vs avg gap
    """
    if total_orders == 0 or aov <= 0.0:
        return 0.0

    # Purchase rate (orders per year)
    tenure_years = max(tenure_days / 365.0, 0.01)
    purchase_rate = total_orders / tenure_years

    # Average inter-purchase gap
    if total_orders > 1:
        avg_gap = tenure_days / (total_orders - 1)
    else:
        avg_gap = tenure_days if tenure_days > 0 else 365.0

    # Alive probability via exponential decay
    # P(alive) = exp(-lambda * overshoot)
    # where overshoot = max(0, days_since_last - avg_gap)
    overshoot = max(0.0, days_since_last - avg_gap)
    decay_rate = 0.01  # lambda — controls how fast churn grows with overshoot
    alive_prob = math.exp(-decay_rate * overshoot)

    # Expected remaining lifetime (years), capped
    if alive_prob > 0.1:
        expected_lifetime = min(3.0, 1.0 / (1.0 - alive_prob + 0.01))
    else:
        expected_lifetime = 0.25  # minimal future expectation

    future_clv = purchase_rate * aov * expected_lifetime * alive_prob
    return max(future_clv, 0.0)


def _assign_tier(total_clv: float) -> str:
    """Assign a value tier based on total CLV."""
    if total_clv >= _TIER_PLATINUM:
        return "platinum"
    if total_clv >= _TIER_GOLD:
        return "gold"
    if total_clv >= _TIER_SILVER:
        return "silver"
    if total_clv >= _TIER_BRONZE:
        return "bronze"
    return "basic"
