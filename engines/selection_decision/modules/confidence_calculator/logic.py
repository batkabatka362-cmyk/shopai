"""Confidence decision logic — data completeness, signal agreement, calibration.

Converts raw engine outputs into confidence factors that feed the composite
confidence score. Each function returns a score (0-100) plus diagnostics.
"""
from __future__ import annotations

import math
from typing import Any

from .data import (
    SIGNAL_AGREEMENT_THRESHOLDS,
    get_calibration_for_raw,
)


# --------------------------------------------------------------------------- #
#  Required engines and their importance weights for completeness scoring
# --------------------------------------------------------------------------- #
_ENGINE_IMPORTANCE: dict[str, float] = {
    "profitability": 1.0,
    "demand": 1.0,
    "competition": 0.8,
    "risk": 0.9,
    "trend": 0.7,
    "market_size": 0.6,
    "filter": 0.5,
}


def assess_data_completeness(engine_results: dict[str, Any]) -> dict[str, Any]:
    """Evaluate how complete the upstream engine data is.

    Args:
        engine_results: Dict mapping engine names to their result dicts.
            Each engine result should have a 'status' key.

    Returns:
        {score: 0-100, missing_engines: list, coverage_pct: float, details: str}
    """
    present_engines: list[str] = []
    missing_engines: list[str] = []
    weighted_present = 0.0
    weighted_total = 0.0

    for engine_name, importance in _ENGINE_IMPORTANCE.items():
        weighted_total += importance
        result = engine_results.get(engine_name)

        has_data = (
            result is not None
            and isinstance(result, dict)
            and result.get("status") in ("success", "completed")
            and result.get("data") is not None
        )

        if has_data:
            present_engines.append(engine_name)
            weighted_present += importance
        else:
            missing_engines.append(engine_name)

    coverage = (weighted_present / weighted_total * 100) if weighted_total > 0 else 0
    score = round(min(100.0, coverage), 1)

    if score >= 85:
        detail = "Excellent data coverage across all major engines."
    elif score >= 65:
        detail = f"Good coverage but missing: {', '.join(missing_engines)}."
    elif score >= 40:
        detail = f"Partial data. Missing critical engines: {', '.join(missing_engines)}."
    else:
        detail = "Insufficient data for a reliable decision."

    return {
        "score": score,
        "coverage_pct": round(coverage, 1),
        "present_engines": present_engines,
        "missing_engines": missing_engines,
        "details": detail,
    }


def measure_signal_agreement(
    normalized_scores: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    """Measure how consistently engines rank products in the same order.

    Args:
        normalized_scores: {product_id: {engine_name: score_0_100, ...}, ...}

    Returns:
        {score: 0-100, std_dev: float, agreement_level: str, conflicts: list}
    """
    if not normalized_scores or len(normalized_scores) < 2:
        return {
            "score": 50.0,
            "std_dev": 0.0,
            "agreement_level": "insufficient_data",
            "conflicts": [],
        }

    # For each engine, get the ranking of products
    engine_names: set[str] = set()
    for scores in normalized_scores.values():
        engine_names.update(k for k, v in scores.items() if v is not None)

    if len(engine_names) < SIGNAL_AGREEMENT_THRESHOLDS["min_engines_for_agreement"]:
        return {
            "score": 35.0,
            "std_dev": 0.0,
            "agreement_level": "too_few_engines",
            "conflicts": [],
        }

    # Calculate per-product score variance across engines
    product_variances: list[float] = []
    conflicts: list[dict[str, Any]] = []

    for pid, scores in normalized_scores.items():
        valid_scores = [v for v in scores.values() if v is not None]
        if len(valid_scores) < 2:
            continue
        mean = sum(valid_scores) / len(valid_scores)
        variance = sum((s - mean) ** 2 for s in valid_scores) / len(valid_scores)
        product_variances.append(variance)

        # Check critical pairs for disagreement
        for eng_a, eng_b in SIGNAL_AGREEMENT_THRESHOLDS["critical_pairs"]:
            score_a = scores.get(eng_a)
            score_b = scores.get(eng_b)
            if score_a is not None and score_b is not None:
                if abs(score_a - score_b) > 50:
                    conflicts.append({
                        "product_id": pid,
                        "engine_a": eng_a,
                        "engine_b": eng_b,
                        "score_a": score_a,
                        "score_b": score_b,
                        "gap": round(abs(score_a - score_b), 1),
                    })

    if not product_variances:
        return {
            "score": 50.0,
            "std_dev": 0.0,
            "agreement_level": "no_variance_data",
            "conflicts": conflicts,
        }

    avg_std_dev = math.sqrt(sum(product_variances) / len(product_variances))
    max_std = SIGNAL_AGREEMENT_THRESHOLDS["max_acceptable_std_dev"]

    # Lower std_dev = higher agreement score
    agreement_score = max(0.0, 100.0 - (avg_std_dev / max_std * 100))
    agreement_score = round(min(100.0, agreement_score), 1)

    # Penalize for critical-pair conflicts
    conflict_penalty = len(conflicts) * 5.0
    agreement_score = max(0.0, agreement_score - conflict_penalty)

    if agreement_score >= SIGNAL_AGREEMENT_THRESHOLDS["strong_agreement"]:
        level = "strong"
    elif agreement_score >= SIGNAL_AGREEMENT_THRESHOLDS["moderate_agreement"]:
        level = "moderate"
    elif agreement_score >= SIGNAL_AGREEMENT_THRESHOLDS["weak_agreement"]:
        level = "weak"
    else:
        level = "none"

    return {
        "score": round(agreement_score, 1),
        "std_dev": round(avg_std_dev, 2),
        "agreement_level": level,
        "conflicts": conflicts,
    }


def calibrate_confidence(
    raw_confidence: float,
    historical_accuracy: float,
) -> dict[str, Any]:
    """Calibrate raw confidence using historical accuracy data.

    Raw confidence tends to be overoptimistic. This function applies a
    dampening factor based on how accurate past predictions actually were.

    Args:
        raw_confidence: Weighted composite score (0-100).
        historical_accuracy: Past accuracy rate for this category (0-100).

    Returns:
        {calibrated_score, adjustment, calibration_tier, note}
    """
    bench = get_calibration_for_raw(raw_confidence)

    # Blend raw confidence with historical accuracy
    # If historical accuracy is low, pull confidence down
    accuracy_ratio = historical_accuracy / 100.0
    dampening = 0.7 + (accuracy_ratio * 0.3)  # Range: 0.7 to 1.0

    calibrated = raw_confidence * dampening
    calibrated = round(max(0.0, min(100.0, calibrated)), 1)
    adjustment = round(calibrated - raw_confidence, 1)

    if adjustment >= -2:
        note = "Historical accuracy supports this confidence level."
    elif adjustment >= -10:
        note = "Slight downward adjustment based on historical performance."
    else:
        note = "Significant correction — historical accuracy is low for this category."

    return {
        "calibrated_score": calibrated,
        "raw_score": raw_confidence,
        "adjustment": adjustment,
        "dampening_factor": round(dampening, 3),
        "calibration_tier": bench["label"],
        "expected_accuracy": bench["calibrated_accuracy"],
        "note": note,
    }
