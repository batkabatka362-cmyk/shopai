"""Customer Segmentation Engine — churn predictor.

Predicts churn probability for each customer using exponential recency
decay combined with engagement signals. Produces a probability score,
risk level, and estimated days until likely churn.

Model note: Would use Mistral for nuanced churn interpretation.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Risk level thresholds
# ---------------------------------------------------------------------------

_HIGH_RISK = 0.70
_MEDIUM_RISK = 0.40
_LOW_RISK = 0.15


def predict_churn(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict churn probability for all customers.

    Args:
        customers: List of normalized customer dicts.

    Returns:
        Structured dict with list of ChurnPrediction dicts.
    """
    try:
        if not customers:
            return {"status": "success", "predictions": [], "count": 0}

        custs = copy.deepcopy(customers)

        # Compute population-level stats for relative scoring
        pop_stats = _population_stats(custs)

        predictions: list[dict[str, Any]] = []
        for c in custs:
            pred = _predict_one(c, pop_stats)
            predictions.append(pred)

        return {
            "status": "success",
            "predictions": predictions,
            "count": len(predictions),
        }
    except Exception as exc:
        return {
            "status": "error",
            "predictions": [],
            "count": 0,
            "error": f"Churn prediction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Population stats
# ---------------------------------------------------------------------------

def _population_stats(customers: list[dict[str, Any]]) -> dict[str, float]:
    """Compute population-level statistics for relative comparison."""
    orders = [c.get("total_orders", 0) for c in customers]
    emails = [c.get("email_opens", 0) for c in customers]
    days = [c.get("days_since_last", 0) for c in customers]

    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "avg_orders": _mean(orders),
        "avg_email_opens": _mean(emails),
        "avg_days_since": _mean(days),
        "max_days_since": max(days) if days else 1,
    }


# ---------------------------------------------------------------------------
# Single-customer prediction
# ---------------------------------------------------------------------------

def _predict_one(
    c: dict[str, Any],
    pop: dict[str, float],
) -> dict[str, Any]:
    """Predict churn for a single customer."""
    cid = c.get("id", "unknown")
    days_since = int(c.get("days_since_last", 0))
    total_orders = int(c.get("total_orders", 0))
    tenure_days = max(int(c.get("tenure_days", 1)), 1)
    email_opens = int(c.get("email_opens", 0))
    cart_abandons = int(c.get("cart_abandons", 0))

    # --- Recency decay component ---
    # Exponential decay: P_recency = 1 - exp(-lambda * days_since_last)
    # Lambda calibrated so that at avg_days_since, decay ~ 0.3
    avg_gap = max(pop["avg_days_since"], 1.0)
    decay_lambda = -math.log(0.7) / avg_gap  # calibrate: at avg gap, prob=0.3
    recency_prob = 1.0 - math.exp(-decay_lambda * days_since)

    # --- Engagement score (0-1, higher = more engaged = less churn) ---
    # Combines email opens and order frequency relative to population
    email_ratio = (email_opens / max(pop["avg_email_opens"], 1.0))
    order_ratio = (total_orders / max(pop["avg_orders"], 1.0))
    engagement_score = min(1.0, (email_ratio * 0.4 + order_ratio * 0.6))

    # --- Cart abandonment signal ---
    # High abandonment without orders signals disengagement
    if total_orders > 0:
        abandon_ratio = cart_abandons / total_orders
    else:
        abandon_ratio = min(cart_abandons, 5) / 5.0  # normalize for non-buyers
    abandon_signal = min(1.0, abandon_ratio * 0.3)

    # --- Combine into final churn probability ---
    # Weighted combination: recency dominates, engagement dampens, abandonment adds
    raw_prob = (
        recency_prob * 0.55
        + (1.0 - engagement_score) * 0.30
        + abandon_signal * 0.15
    )
    churn_probability = max(0.0, min(1.0, raw_prob))

    # --- Decay factor (raw exponential term) ---
    decay_factor = round(math.exp(-decay_lambda * days_since), 4)

    # --- Risk level ---
    if churn_probability >= _HIGH_RISK:
        risk_level = "high"
    elif churn_probability >= _MEDIUM_RISK:
        risk_level = "medium"
    elif churn_probability >= _LOW_RISK:
        risk_level = "low"
    else:
        risk_level = "minimal"

    # --- Estimated days until likely churn ---
    # Solve for when cumulative probability would cross 0.85
    if churn_probability < 0.85 and decay_lambda > 0:
        target_recency_prob = (0.85 - (1.0 - engagement_score) * 0.30 - abandon_signal * 0.15) / 0.55
        target_recency_prob = max(0.01, min(0.99, target_recency_prob))
        target_days = -math.log(1.0 - target_recency_prob) / decay_lambda
        days_until = max(0, int(target_days - days_since))
    else:
        days_until = 0

    return {
        "customer_id": cid,
        "churn_probability": round(churn_probability, 4),
        "risk_level": risk_level,
        "decay_factor": decay_factor,
        "engagement_score": round(engagement_score, 4),
        "days_until_likely_churn": days_until,
    }
