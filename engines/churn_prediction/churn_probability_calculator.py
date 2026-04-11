"""Churn Prediction Engine — churn probability calculator.

Calculates overall churn probability using a weighted combination of
risk signals from upstream pipeline stages.

Weights:
  - recency:           0.30
  - frequency_change:  0.25
  - engagement_drop:   0.20
  - aov_decline:       0.15
  - support_issues:    0.10

Model note: no model usage — deterministic weighted calculation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Feature weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, float] = {
    "recency": 0.30,
    "frequency_change": 0.25,
    "engagement_drop": 0.20,
    "aov_decline": 0.15,
    "support_issues": 0.10,
}


def calculate_churn_probability(
    features: dict[str, Any],
    recency: dict[str, Any],
    engagement: dict[str, Any],
    pattern: dict[str, Any],
) -> dict[str, Any]:
    """Calculate churn probability from all upstream risk signals.

    Args:
        features: ExtractedFeatures from feature_extractor.
        recency: RecencyAnalysis from recency_analyzer.
        engagement: EngagementScore from engagement_scorer.
        pattern: PurchasePattern from purchase_pattern_detector.

    Returns:
        Structured dict with ChurnProbability data and status.
    """
    try:
        safe_features = copy.deepcopy(features)
        safe_recency = copy.deepcopy(recency)
        safe_engagement = copy.deepcopy(engagement)
        safe_pattern = copy.deepcopy(pattern)

        # --- Recency factor ---
        # recency_risk is already 0..1 from recency_analyzer
        recency_factor = float(safe_recency.get("recency_risk", 0.0))
        recency_factor = _clamp(recency_factor)

        # --- Frequency change factor ---
        # frequency_change is negative when declining; convert to 0..1 risk
        frequency_change = float(safe_pattern.get("frequency_change", 0.0))
        frequency_factor = _clamp(-frequency_change)  # more negative = higher risk

        # --- Engagement drop factor ---
        # composite_score is 0..1 where 1 = fully engaged
        composite_score = float(safe_engagement.get("composite_score", 0.5))
        engagement_factor = _clamp(1.0 - composite_score)

        # --- AOV decline factor ---
        # aov_trend is negative when declining; convert to 0..1 risk
        aov_trend = float(safe_pattern.get("aov_trend", 0.0))
        aov_factor = _clamp(-aov_trend)

        # --- Support issues factor ---
        support_tickets = int(safe_features.get("support_tickets", 0))
        # Normalize: 3+ tickets = max risk
        support_factor = _clamp(support_tickets / 3.0)

        # --- Weighted combination ---
        contributions: dict[str, float] = {
            "recency": round(_WEIGHTS["recency"] * recency_factor, 4),
            "frequency_change": round(_WEIGHTS["frequency_change"] * frequency_factor, 4),
            "engagement_drop": round(_WEIGHTS["engagement_drop"] * engagement_factor, 4),
            "aov_decline": round(_WEIGHTS["aov_decline"] * aov_factor, 4),
            "support_issues": round(_WEIGHTS["support_issues"] * support_factor, 4),
        }

        probability = round(sum(contributions.values()), 4)
        probability = _clamp(probability)

        return {
            "status": "success",
            "churn": {
                "probability": probability,
                "factor_contributions": contributions,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "churn": {},
            "error": f"Churn probability calculation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a value to [low, high]."""
    return max(low, min(high, value))
