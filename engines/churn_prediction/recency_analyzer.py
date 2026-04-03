"""Churn Prediction Engine — recency analyzer.

Analyzes purchase recency using an exponential decay model.  Compares
each customer's gap since last purchase against their personal baseline
(derived from order frequency) and a population average.

Decay formula:
    decay_score = exp(-lambda * days_since_last)

where lambda is calibrated so that a gap equal to the customer's average
purchase interval yields a decay of ~0.5 (the half-life point).

Model note: no model usage — deterministic mathematical analysis.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Population baseline (configurable defaults)
# ---------------------------------------------------------------------------

_POPULATION_AVG_DAYS_BETWEEN_PURCHASES = 30.0
_POPULATION_AVG_ORDER_FREQUENCY = 1.0  # orders per 30 days


def analyze_recency(
    features: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Analyze purchase recency via exponential decay.

    Args:
        features: ExtractedFeatures from feature_extractor.
        customer: Original customer record.

    Returns:
        Structured dict with RecencyAnalysis data and status.
    """
    try:
        safe_features = copy.deepcopy(features)
        safe_customer = copy.deepcopy(customer)

        days_since_last = int(safe_features.get("days_since_last", 0))
        order_frequency = float(safe_features.get("order_frequency", 0.0))
        account_age_days = int(safe_customer.get("account_age_days", 1))
        total_orders = int(safe_customer.get("total_orders", 0))

        # --- Personal baseline: average days between purchases ---
        if total_orders > 1 and account_age_days > 0:
            personal_avg_interval = account_age_days / (total_orders - 1)
        elif total_orders == 1:
            personal_avg_interval = float(account_age_days)
        else:
            personal_avg_interval = _POPULATION_AVG_DAYS_BETWEEN_PURCHASES

        # Guard against zero or negative intervals
        personal_avg_interval = max(personal_avg_interval, 1.0)

        # --- Exponential decay ---
        # Set lambda so that decay = 0.5 at the personal average interval
        # exp(-lambda * interval) = 0.5  =>  lambda = ln(2) / interval
        decay_lambda = math.log(2.0) / personal_avg_interval
        decay_score = math.exp(-decay_lambda * days_since_last)
        decay_score = round(max(0.0, min(1.0, decay_score)), 4)

        # --- Personal baseline ratio ---
        # How many multiples of the personal interval has elapsed?
        personal_baseline_ratio = round(
            days_since_last / personal_avg_interval, 4
        )

        # --- Population ratio ---
        population_ratio = round(
            days_since_last / _POPULATION_AVG_DAYS_BETWEEN_PURCHASES, 4
        )

        # --- Combined recency risk ---
        # Higher values = higher risk.  Decay close to 0 means long gap.
        # Personal baseline ratio > 1 means overdue.
        risk_from_decay = 1.0 - decay_score
        risk_from_baseline = min(personal_baseline_ratio / 3.0, 1.0)
        risk_from_population = min(population_ratio / 3.0, 1.0)

        recency_risk = round(
            risk_from_decay * 0.50
            + risk_from_baseline * 0.30
            + risk_from_population * 0.20,
            4,
        )
        recency_risk = max(0.0, min(1.0, recency_risk))

        return {
            "status": "success",
            "recency": {
                "decay_score": decay_score,
                "personal_baseline_ratio": personal_baseline_ratio,
                "population_ratio": population_ratio,
                "recency_risk": recency_risk,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "recency": {},
            "error": f"Recency analysis failed: {exc}",
        }
