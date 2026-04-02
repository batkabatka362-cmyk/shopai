"""A/B Testing -- risk assessor.

Assesses the risk of implementing the winning variant:
  - Novelty effect risk (early excitement fading over time)
  - Segment differences (winner may not hold across all segments)
  - Long-term impact (short test may miss long-term trends)

Model note: Would use LLaMA for nuanced risk narrative generation
            and mitigation strategy suggestions.
"""
from __future__ import annotations

from typing import Any


def assess_risk(
    winner: dict[str, Any],
    analysis: dict[str, Any],
    metrics: list[dict[str, Any]],
    test_type: str,
    segments: list[str] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess risk of implementing the A/B test winner.

    Args:
        winner: Winner selection result.
        analysis: Statistical analysis result.
        metrics: Per-variant metric dicts.
        test_type: Category of test (pricing, content, ads, ux).
        segments: Audience segments to consider.
        history: Past test results for context.

    Returns:
        Structured dict with risk assessment.
    """
    try:
        segments = segments or []
        history = history or []

        recommendation = str(winner.get("recommendation", ""))
        winner_confidence = float(winner.get("confidence", 0.0))
        p_value = float(analysis.get("p_value", 1.0))
        effect_size = abs(float(analysis.get("effect_size", 0.0)))
        power_achieved = float(analysis.get("power_achieved", 0.0))

        # ---- Novelty effect risk ----
        novelty_risk = _assess_novelty_risk(
            test_type=test_type,
            effect_size=effect_size,
            recommendation=recommendation,
        )

        # ---- Segment differences risk ----
        segment_risk = _assess_segment_risk(
            segments=segments,
            metrics=metrics,
        )

        # ---- Long-term impact risk ----
        long_term_risk = _assess_long_term_risk(
            test_type=test_type,
            power_achieved=power_achieved,
            history=history,
        )

        # ---- Compile risk factors ----
        risk_factors: list[dict[str, Any]] = []

        if novelty_risk > 0.3:
            risk_factors.append({
                "name": "Novelty Effect",
                "severity": round(novelty_risk, 2),
                "likelihood": round(min(1.0, novelty_risk * 1.2), 2),
                "description": (
                    "Initial user excitement may inflate early metrics. "
                    "The observed lift could partially fade after full rollout."
                ),
            })

        if segment_risk > 0.3:
            risk_factors.append({
                "name": "Segment Variation",
                "severity": round(segment_risk, 2),
                "likelihood": round(min(1.0, segment_risk * 1.1), 2),
                "description": (
                    "Test results may not generalize equally across all "
                    "audience segments. Some segments could see neutral or "
                    "negative impact."
                ),
            })

        if long_term_risk > 0.3:
            risk_factors.append({
                "name": "Long-Term Impact",
                "severity": round(long_term_risk, 2),
                "likelihood": round(min(1.0, long_term_risk * 1.0), 2),
                "description": (
                    "Short test duration may not capture seasonal patterns, "
                    "user adaptation, or cumulative effects."
                ),
            })

        # Low power is always a risk
        if power_achieved < 0.80:
            risk_factors.append({
                "name": "Low Statistical Power",
                "severity": round(1.0 - power_achieved, 2),
                "likelihood": 0.7,
                "description": (
                    f"Achieved power ({power_achieved:.2f}) is below the "
                    f"recommended 0.80 threshold, increasing the chance of "
                    f"a false negative or unreliable effect estimate."
                ),
            })

        # ---- Overall risk ----
        overall_risk = _compute_overall_risk(
            novelty_risk, segment_risk, long_term_risk, power_achieved,
        )
        risk_level = _risk_level(overall_risk)

        # ---- Mitigation suggestions ----
        mitigations = _suggest_mitigations(
            risk_factors=risk_factors,
            recommendation=recommendation,
            test_type=test_type,
        )

        risk_assessment = {
            "overall_risk": round(overall_risk, 4),
            "risk_level": risk_level,
            "novelty_effect_risk": round(novelty_risk, 4),
            "segment_risk": round(segment_risk, 4),
            "long_term_risk": round(long_term_risk, 4),
            "risk_factors": risk_factors,
            "mitigation_suggestions": mitigations,
            "model_note": (
                "LLaMA would generate nuanced risk narratives, draw on "
                "domain knowledge of the test_type, and produce tailored "
                "mitigation strategies"
            ),
        }

        return {
            "status": "success",
            "risk": risk_assessment,
        }
    except Exception as exc:
        return {
            "status": "error",
            "risk": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Individual risk assessments
# ---------------------------------------------------------------------------

def _assess_novelty_risk(
    test_type: str,
    effect_size: float,
    recommendation: str,
) -> float:
    """Estimate novelty effect risk.

    UX and content changes are more susceptible to novelty effects.
    Very large effect sizes are more likely to be inflated by novelty.
    """
    base = 0.15

    # Test type modifier
    type_modifiers = {
        "ux": 0.25,
        "content": 0.20,
        "ads": 0.15,
        "pricing": 0.05,
    }
    base += type_modifiers.get(test_type, 0.10)

    # Large effects are more suspect
    if effect_size > 0.05:
        base += 0.15
    elif effect_size > 0.02:
        base += 0.05

    # If no clear winner, novelty risk is lower
    if recommendation != "implement":
        base *= 0.5

    return min(1.0, base)


def _assess_segment_risk(
    segments: list[str],
    metrics: list[dict[str, Any]],
) -> float:
    """Estimate risk from segment-level variation.

    More segments means more potential for heterogeneous treatment effects.
    """
    if not segments:
        # No segments defined -- moderate unknown risk
        return 0.35

    # More segments = more risk of heterogeneous effects
    base = min(1.0, 0.20 + len(segments) * 0.08)

    return min(1.0, base)


def _assess_long_term_risk(
    test_type: str,
    power_achieved: float,
    history: list[dict[str, Any]],
) -> float:
    """Estimate long-term implementation risk.

    Pricing changes carry more long-term risk than content changes.
    Low power suggests the test may not have run long enough.
    """
    base = 0.20

    type_modifiers = {
        "pricing": 0.30,
        "ux": 0.15,
        "content": 0.05,
        "ads": 0.10,
    }
    base += type_modifiers.get(test_type, 0.10)

    # Low power suggests insufficient data
    if power_achieved < 0.80:
        base += 0.15

    # No historical context increases risk
    if not history:
        base += 0.10

    return min(1.0, base)


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _compute_overall_risk(
    novelty: float,
    segment: float,
    long_term: float,
    power: float,
) -> float:
    """Weighted average of risk components."""
    power_penalty = max(0.0, (0.80 - power) * 0.5) if power < 0.80 else 0.0

    overall = (
        0.25 * novelty
        + 0.30 * segment
        + 0.30 * long_term
        + 0.15 * power_penalty
    )
    return min(1.0, max(0.0, overall))


def _risk_level(risk: float) -> str:
    """Map a numeric risk score to a label."""
    if risk < 0.30:
        return "low"
    if risk < 0.60:
        return "medium"
    return "high"


def _suggest_mitigations(
    risk_factors: list[dict[str, Any]],
    recommendation: str,
    test_type: str,
) -> list[str]:
    """Generate mitigation suggestions based on identified risks."""
    suggestions: list[str] = []

    factor_names = {rf.get("name", "") for rf in risk_factors}

    if "Novelty Effect" in factor_names:
        suggestions.append(
            "Run a holdback test after implementation -- keep 5-10% of traffic "
            "on the old experience for 2-4 weeks to detect novelty decay."
        )

    if "Segment Variation" in factor_names:
        suggestions.append(
            "Analyze results by segment before full rollout. Consider a "
            "phased rollout starting with the highest-confidence segments."
        )

    if "Long-Term Impact" in factor_names:
        suggestions.append(
            "Monitor key metrics weekly for at least 4 weeks post-rollout. "
            "Set automated alerts for significant metric degradation."
        )

    if "Low Statistical Power" in factor_names:
        suggestions.append(
            "Consider extending the test duration or increasing traffic "
            "allocation to achieve power >= 0.80 before making a decision."
        )

    if recommendation == "implement" and test_type == "pricing":
        suggestions.append(
            "For pricing changes, implement with a gradual rollout (25% -> "
            "50% -> 100%) over 2 weeks, monitoring revenue and churn closely."
        )

    if not suggestions:
        suggestions.append(
            "No major risks identified. Proceed with standard rollout "
            "and post-implementation monitoring."
        )

    return suggestions
