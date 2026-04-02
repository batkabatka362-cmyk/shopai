"""Email Marketing Engine — performance predictor.

Predicts open rate, click rate, conversion rate, and unsubscribe rate
based on audience composition, content quality signals, and campaign
type benchmarks.

Model note: Uses Mistral for analytical performance prediction.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Industry benchmarks by campaign type (baseline rates)
# ---------------------------------------------------------------------------

_BENCHMARKS: dict[str, dict[str, float]] = {
    "promotional": {
        "open_rate": 0.18,
        "click_rate": 0.025,
        "conversion_rate": 0.012,
        "unsubscribe_rate": 0.003,
    },
    "nurture": {
        "open_rate": 0.22,
        "click_rate": 0.030,
        "conversion_rate": 0.008,
        "unsubscribe_rate": 0.001,
    },
    "win-back": {
        "open_rate": 0.14,
        "click_rate": 0.018,
        "conversion_rate": 0.010,
        "unsubscribe_rate": 0.005,
    },
    "announcement": {
        "open_rate": 0.24,
        "click_rate": 0.035,
        "conversion_rate": 0.006,
        "unsubscribe_rate": 0.002,
    },
}

# Segment engagement multipliers (applied to open and click rates)
_SEGMENT_MULTIPLIERS: dict[str, float] = {
    "vip": 1.45,
    "active": 1.20,
    "new": 1.05,
    "lapsed": 0.65,
    "at_risk": 0.50,
    "dormant": 0.30,
}


def predict_performance(
    goal: str,
    audience_selection: dict[str, Any],
    subject_lines: dict[str, Any],
    body: dict[str, Any],
    discount: dict[str, Any],
) -> dict[str, Any]:
    """Predict campaign performance metrics.

    Args:
        goal: Campaign goal / type.
        audience_selection: AudienceSelection from audience_selector.
        subject_lines: SubjectLineSet from subject_line_generator.
        body: EmailBody from body_composer.
        discount: DiscountInfo dict.

    Returns:
        Structured dict with PerformancePrediction data.
    """
    try:
        goal_key = str(goal).lower().strip()
        audience = copy.deepcopy(audience_selection)
        subj = copy.deepcopy(subject_lines)

        # Start from benchmarks
        benchmarks = copy.deepcopy(
            _BENCHMARKS.get(goal_key, _BENCHMARKS["promotional"])
        )
        open_rate = benchmarks["open_rate"]
        click_rate = benchmarks["click_rate"]
        conversion_rate = benchmarks["conversion_rate"]
        unsubscribe_rate = benchmarks["unsubscribe_rate"]

        factors: list[str] = []

        # Factor 1: Audience quality — weighted average of segment multipliers
        engagement_priority = audience.get("engagement_priority", [])
        if engagement_priority:
            weighted_mult = _weighted_segment_multiplier(engagement_priority)
            open_rate *= weighted_mult
            click_rate *= weighted_mult
            factors.append(
                f"Audience quality multiplier: {weighted_mult:.2f}"
            )

        # Factor 2: Subject line quality — use best subject score
        subject_line_list = subj.get("subject_lines", [])
        if subject_line_list:
            best_score = max(s.get("score", 0.5) for s in subject_line_list)
            # Score above 0.7 boosts; below 0.5 penalizes
            subject_lift = 1.0 + (best_score - 0.65) * 0.5
            open_rate *= subject_lift
            factors.append(
                f"Best subject line score: {best_score:.2f} (lift: {subject_lift:.2f}x)"
            )

        # Factor 3: Discount presence boosts conversion
        if discount and discount.get("value", 0) > 0:
            disc_val = discount.get("value", 0)
            disc_type = discount.get("type", "percentage")
            if disc_type == "percentage" and disc_val >= 15:
                conversion_rate *= 1.35
                click_rate *= 1.15
                factors.append(f"Strong discount ({disc_val}% off) boosts conversion +35%")
            elif disc_val > 0:
                conversion_rate *= 1.15
                factors.append(f"Discount present ({disc_val}) boosts conversion +15%")

        # Factor 4: Product count — more products = more click opportunities
        product_blocks = body.get("product_blocks", [])
        if len(product_blocks) >= 3:
            click_rate *= 1.10
            factors.append(f"{len(product_blocks)} products improve click rate +10%")

        # Factor 5: Personalization in subject line reduces unsubscribe
        has_personalized = any(
            s.get("personalized", False) for s in subject_line_list
        )
        if has_personalized:
            unsubscribe_rate *= 0.80
            open_rate *= 1.08
            factors.append("Personalized subject lines reduce unsub -20%, lift opens +8%")

        # Clamp rates to reasonable bounds
        open_rate = _clamp(open_rate, 0.05, 0.65)
        click_rate = _clamp(click_rate, 0.005, 0.15)
        conversion_rate = _clamp(conversion_rate, 0.001, 0.08)
        unsubscribe_rate = _clamp(unsubscribe_rate, 0.0005, 0.02)

        # Confidence: based on how many factors we could evaluate
        max_factors = 5
        confidence = min(len(factors) / max_factors, 1.0)
        confidence = round(confidence * 0.85 + 0.10, 2)  # range 0.10 – 0.95

        return {
            "status": "success",
            "prediction": {
                "open_rate": round(open_rate, 4),
                "click_rate": round(click_rate, 4),
                "conversion_rate": round(conversion_rate, 4),
                "unsubscribe_rate": round(unsubscribe_rate, 4),
                "confidence": confidence,
                "factors": factors,
                "model_note": "Mistral: analytical performance prediction with benchmarks",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "prediction": {},
            "error": f"Performance prediction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _weighted_segment_multiplier(
    engagement_priority: list[dict[str, Any]],
) -> float:
    """Compute weighted average multiplier based on segment sizes."""
    total_size = 0
    weighted_sum = 0.0

    for entry in engagement_priority:
        seg = entry.get("segment", "")
        net_size = entry.get("net_size", 0)
        mult = _SEGMENT_MULTIPLIERS.get(seg, 1.0)
        weighted_sum += mult * net_size
        total_size += net_size

    if total_size == 0:
        return 1.0
    return weighted_sum / total_size


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp a value to [low, high]."""
    return max(low, min(value, high))
