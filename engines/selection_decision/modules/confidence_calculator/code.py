"""Confidence calculation engine — quantifies certainty in product selection.

Main entry point: calculate_confidence(input_payload)
Returns engine contract: {status, data, meta, error}

Factors:
  Data quality      — how complete is the upstream data? (0-100)
  Signal agreement  — do engines agree on the ranking? (0-100)
  Historical accuracy — past selections accuracy rate (0-100)
  Score gap         — clear winner vs. close race (0-100)
  Composite         — weighted average → low / medium / high classification
"""
from __future__ import annotations

import time
from typing import Any

from .data import CONFIDENCE_WEIGHTS, get_calibration_for_raw, get_historical_baseline
from .logic import assess_data_completeness, measure_signal_agreement, calibrate_confidence
from .rules import evaluate_confidence_rules


def calculate_confidence(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate composite confidence for a product selection decision.

    Args:
        input_payload: {
            ranked_products: list[dict] — products with unified_score and engine data
            engine_results: dict        — raw results from upstream engines
            category: str               — product category (for historical baselines)
            goal: str                   — profit|growth|balanced
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    start = time.time()

    try:
        ranked = input_payload.get("ranked_products", [])
        engine_results = input_payload.get("engine_results", {})
        category = input_payload.get("category", "general")

        if not ranked:
            return _error("ranked_products is required and must be non-empty", start)

        # --- Factor 1: Data quality (0-100) ---
        data_quality = assess_data_completeness(engine_results)

        # --- Factor 2: Signal agreement (0-100) ---
        scores = {
            p.get("product_id", f"p{i}"): p.get("unified_score", 0)
            for i, p in enumerate(ranked)
        }
        normalized_scores = {
            p.get("product_id", f"p{i}"): p.get("normalized_scores", {})
            for i, p in enumerate(ranked)
        }
        signal_agreement = measure_signal_agreement(normalized_scores)

        # --- Factor 3: Historical accuracy (0-100) ---
        baseline = get_historical_baseline(category)
        historical_accuracy = baseline["accuracy"]

        # --- Factor 4: Score gap (0-100) ---
        score_gap = _compute_score_gap(ranked)

        # --- Composite confidence ---
        raw_composite = (
            data_quality["score"] * CONFIDENCE_WEIGHTS["data_quality"]
            + signal_agreement["score"] * CONFIDENCE_WEIGHTS["signal_agreement"]
            + historical_accuracy * CONFIDENCE_WEIGHTS["historical_accuracy"]
            + score_gap["score"] * CONFIDENCE_WEIGHTS["score_gap"]
        )
        raw_composite = round(raw_composite, 1)

        calibrated = calibrate_confidence(raw_composite, historical_accuracy)
        classification = _classify_confidence(calibrated["calibrated_score"])

        # --- Rules evaluation ---
        rules_result = evaluate_confidence_rules({
            "composite_score": calibrated["calibrated_score"],
            "data_quality_score": data_quality["score"],
            "signal_agreement_score": signal_agreement["score"],
            "score_gap": score_gap["gap_pct"],
        })

        data = {
            "composite_confidence": calibrated["calibrated_score"],
            "raw_confidence": raw_composite,
            "classification": classification,
            "factors": {
                "data_quality": data_quality,
                "signal_agreement": signal_agreement,
                "historical_accuracy": {
                    "score": historical_accuracy,
                    "category": category,
                    "sample_size": baseline["sample_size"],
                },
                "score_gap": score_gap,
            },
            "calibration": calibrated,
            "rules": rules_result,
            "recommendation": _build_recommendation(classification, rules_result),
        }

        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "confidence_calculator",
                "duration_ms": round((time.time() - start) * 1000, 2),
                "products_evaluated": len(ranked),
                "category": category,
            },
            "error": None,
        }

    except (ValueError, KeyError, TypeError) as exc:
        return _error(str(exc), start)


def _compute_score_gap(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure the gap between the top-ranked product and the runner-up."""
    if len(ranked) < 2:
        return {"score": 80.0, "gap_pct": 100.0, "description": "Single product — no comparison needed"}

    top_score = ranked[0].get("unified_score", 0)
    second_score = ranked[1].get("unified_score", 0)

    if top_score == 0:
        return {"score": 0.0, "gap_pct": 0.0, "description": "Top product has zero score"}

    gap_pct = round(((top_score - second_score) / top_score) * 100, 1)

    if gap_pct >= 25:
        factor_score = 95.0
        desc = f"Clear winner — {gap_pct}% gap. High confidence in ranking."
    elif gap_pct >= 15:
        factor_score = 75.0
        desc = f"Solid lead — {gap_pct}% gap. Comfortable margin."
    elif gap_pct >= 8:
        factor_score = 55.0
        desc = f"Moderate gap — {gap_pct}%. Products are competitive."
    elif gap_pct >= 3:
        factor_score = 30.0
        desc = f"Tight race — {gap_pct}% gap. Either product could win."
    else:
        factor_score = 10.0
        desc = f"Virtual tie — {gap_pct}% gap. Selection is arbitrary."

    return {"score": factor_score, "gap_pct": gap_pct, "description": desc}


def _classify_confidence(score: float) -> dict[str, str]:
    """Classify composite confidence into low/medium/high."""
    if score >= 70:
        return {"level": "high", "label": "Auto-proceed", "color": "green"}
    elif score >= 40:
        return {"level": "medium", "label": "Proceed with monitoring", "color": "yellow"}
    else:
        return {"level": "low", "label": "Requires human review", "color": "red"}


def _build_recommendation(
    classification: dict[str, str],
    rules_result: dict[str, Any],
) -> dict[str, Any]:
    """Build an actionable recommendation based on confidence and rules."""
    level = classification["level"]
    has_blockers = len(rules_result.get("blockers", [])) > 0

    if has_blockers:
        action = "halt"
        message = "Blockers detected. Do not proceed until resolved."
    elif level == "high":
        action = "auto_proceed"
        message = "Confidence is high. Proceed with standard order quantity."
    elif level == "medium":
        action = "proceed_with_monitoring"
        message = "Confidence is moderate. Proceed with reduced order and 2-week review."
    else:
        action = "human_review"
        message = "Confidence is low. Escalate to human review before ordering."

    return {"action": action, "message": message, "confidence_level": level}


def _error(message: str, start: float) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {
            "module": "confidence_calculator",
            "duration_ms": round((time.time() - start) * 1000, 2),
        },
        "error": {"type": "ConfidenceError", "message": message},
    }
