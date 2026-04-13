"""Churn Prediction Engine — risk classifier.

Classifies churn probability into a discrete risk level with human-readable
descriptions.  Thresholds are fixed and deterministic.

Risk levels:
  - critical:  probability > 0.8
  - high:      probability > 0.6
  - medium:    probability > 0.4
  - low:       probability > 0.2
  - minimal:   probability <= 0.2

Model note: no model usage — deterministic threshold classification.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Risk tier definitions (ordered highest to lowest)
# ---------------------------------------------------------------------------

_RISK_TIERS: list[tuple[float, str, str]] = [
    (0.8, "critical", "Imminent churn — customer is nearly lost and requires immediate intervention"),
    (0.6, "high", "Serious churn risk — significant disengagement detected across multiple signals"),
    (0.4, "medium", "Moderate churn risk — early warning signs present, proactive action recommended"),
    (0.2, "low", "Low churn risk — minor signals detected but customer remains mostly engaged"),
    (0.0, "minimal", "Minimal churn risk — customer shows healthy engagement and purchase patterns"),
]


def classify_risk(churn_probability: float) -> dict[str, Any]:
    """Classify a churn probability into a named risk level.

    Args:
        churn_probability: Float 0.0-1.0 from churn_probability_calculator.

    Returns:
        Structured dict with RiskClassification data and status.
    """
    try:
        probability = max(0.0, min(1.0, float(churn_probability)))

        for threshold, level, description in _RISK_TIERS:
            if probability > threshold:
                return {
                    "status": "success",
                    "classification": {
                        "level": level,
                        "threshold": threshold,
                        "description": description,
                    },
                }

        # Fallback (probability == 0.0 exactly)
        return {
            "status": "success",
            "classification": {
                "level": "minimal",
                "threshold": 0.0,
                "description": _RISK_TIERS[-1][2],
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "classification": {},
            "error": f"Risk classification failed: {exc}",
        }
