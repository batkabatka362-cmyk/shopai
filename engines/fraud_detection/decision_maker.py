"""Fraud Detection Engine — decision maker.

Combines all signal scores with configurable weights to produce a final
risk score, risk level, verdict, and confidence value.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Signal weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, float] = {
    "base_risk": 0.20,
    "velocity": 0.15,
    "address": 0.20,
    "pattern": 0.20,
    "blacklist": 0.15,
    "device": 0.10,
}

# ---------------------------------------------------------------------------
# Risk level thresholds
# ---------------------------------------------------------------------------

_LEVEL_LOW = 0.3
_LEVEL_MEDIUM = 0.6
_LEVEL_HIGH = 0.8


def make_decision(
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Combine signal scores into a final fraud verdict.

    Args:
        signals: Dict mapping signal names to their result dicts,
                 each containing at least a 'score' key (0.0-1.0).

    Returns:
        Structured dict with verdict, risk_score, risk_level, and confidence.
    """
    try:
        signals = copy.deepcopy(signals)

        weighted_sum = 0.0
        total_weight = 0.0
        available_signals = 0
        signal_scores: dict[str, float] = {}

        for signal_name, weight in _WEIGHTS.items():
            signal_data = signals.get(signal_name, {})
            if not isinstance(signal_data, dict):
                continue

            if signal_data.get("status") == "error":
                # Skip errored signals — don't penalize for missing data
                continue

            score = float(signal_data.get("score", 0.0))
            score = max(0.0, min(1.0, score))

            weighted_sum += score * weight
            total_weight += weight
            available_signals += 1
            signal_scores[signal_name] = score

        # Normalize to account for missing signals
        if total_weight > 0:
            risk_score = round(weighted_sum / total_weight, 4)
        else:
            risk_score = 0.0

        risk_score = max(0.0, min(1.0, risk_score))

        # Blacklist override: any blacklist hit forces minimum high risk
        blacklist_data = signals.get("blacklist", {})
        if isinstance(blacklist_data, dict) and blacklist_data.get("status") == "success":
            any_listed = (
                blacklist_data.get("email_listed", False)
                or blacklist_data.get("ip_listed", False)
                or blacklist_data.get("phone_listed", False)
                or blacklist_data.get("address_listed", False)
            )
            if any_listed:
                risk_score = max(risk_score, _LEVEL_HIGH)

        # Determine risk level
        if risk_score < _LEVEL_LOW:
            risk_level = "low"
        elif risk_score < _LEVEL_MEDIUM:
            risk_level = "medium"
        elif risk_score < _LEVEL_HIGH:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Determine verdict
        if risk_level in ("low", "medium"):
            verdict = "approve"
        elif risk_level == "high":
            verdict = "review"
        else:
            verdict = "reject"

        # Confidence: based on how many signals we had data for
        expected_signals = len(_WEIGHTS)
        confidence = round(available_signals / expected_signals, 4) if expected_signals > 0 else 0.0

        # Adjust confidence down if scores are clustered near the boundary
        if risk_level == "medium" and abs(risk_score - _LEVEL_LOW) < 0.05:
            confidence *= 0.85
        elif risk_level == "medium" and abs(risk_score - _LEVEL_MEDIUM) < 0.05:
            confidence *= 0.85
        elif risk_level == "high" and abs(risk_score - _LEVEL_MEDIUM) < 0.05:
            confidence *= 0.85

        confidence = round(max(0.0, min(1.0, confidence)), 4)

        return {
            "status": "success",
            "verdict": verdict,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence": confidence,
        }
    except Exception as exc:
        return {
            "status": "error",
            "verdict": "review",
            "risk_score": 0.5,
            "risk_level": "medium",
            "confidence": 0.0,
            "error": f"Decision making failed: {exc}",
        }
