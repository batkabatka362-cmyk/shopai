"""Pricing Engine — price recommender.

Produces the final pricing recommendation by synthesizing results from
all prior pipeline stages: cost analysis, competitor mapping, value
estimation, price calculation, margin validation, psychology optimization,
and elasticity estimation.

Model note: Uses Qwen for structured pricing plan generation.
"""
from __future__ import annotations

import copy
from typing import Any


def recommend_price(
    psychology_adjustment: dict[str, Any],
    margin_validation: dict[str, Any],
    price_calculation: dict[str, Any],
    cost_analysis: dict[str, Any],
    competitor_mapping: dict[str, Any],
    value_estimate: dict[str, Any],
    elasticity: dict[str, Any],
    target_margin: float,
) -> dict[str, Any]:
    """Produce the final pricing recommendation.

    Args:
        psychology_adjustment: PsychologyAdjustment from optimizer.
        margin_validation: MarginCheck from validator.
        price_calculation: PriceCalculation from calculator.
        cost_analysis: CostAnalysis from analyzer.
        competitor_mapping: CompetitorPrices from mapper.
        value_estimate: ValueEstimate from estimator.
        elasticity: ElasticityEstimate from elasticity estimator.
        target_margin: Original target margin.

    Returns:
        Structured dict with PriceRecommendation data.
    """
    try:
        psych = copy.deepcopy(psychology_adjustment)
        margin = copy.deepcopy(margin_validation)
        calc = copy.deepcopy(price_calculation)
        costs = copy.deepcopy(cost_analysis)
        comp = copy.deepcopy(competitor_mapping)
        value = copy.deepcopy(value_estimate)
        elast = copy.deepcopy(elasticity)

        # --- Optimal price: use psychology-adjusted price ---
        optimal_price = float(psych.get("adjusted_price", 0.0))

        # If psychology adjustment failed, fall back to weighted price
        if optimal_price <= 0:
            optimal_price = float(calc.get("weighted_price", 0.0))

        # --- Price range ---
        floor_price = float(margin.get("floor_price", costs.get("cost_floor", 0.0)))
        ceiling_price = float(margin.get("ceiling_price", 0.0))
        price_range = {
            "floor": round(floor_price, 2),
            "ceiling": round(ceiling_price, 2),
        }

        # --- Strategy ---
        strategy = str(calc.get("recommended_strategy", "cost_plus"))

        # --- Projected margin at optimal price ---
        total_cost = float(costs.get("total_cost", 0.0))
        if optimal_price > 0:
            projected_margin = (optimal_price - total_cost) / optimal_price
        else:
            projected_margin = 0.0

        # --- Competitive position ---
        avg_price = float(comp.get("avg_price", 0.0))
        competitive_position = _determine_position(optimal_price, avg_price)

        # --- Confidence ---
        # Blend: value confidence (40%), margin health (30%), data richness (30%)
        value_confidence = float(value.get("value_confidence", 0.5))
        margin_health = margin.get("margin_health", "unknown")
        margin_conf = _margin_health_to_confidence(margin_health)
        competitor_count = int(comp.get("competitor_count", 0))
        data_conf = min(competitor_count / 10.0, 1.0)

        confidence = (
            value_confidence * 0.4
            + margin_conf * 0.3
            + data_conf * 0.3
        )
        confidence = round(min(max(confidence, 0.0), 1.0), 2)

        # --- Rationale ---
        rationale = _build_rationale(
            optimal_price=optimal_price,
            strategy=strategy,
            projected_margin=projected_margin,
            target_margin=target_margin,
            competitive_position=competitive_position,
            psychology_technique=psych.get("technique_applied", "none"),
            sensitivity=elast.get("sensitivity", "medium"),
            cost_floor=floor_price,
            ceiling=ceiling_price,
        )

        return {
            "status": "success",
            "recommendation": {
                "optimal_price": round(optimal_price, 2),
                "price_range": price_range,
                "strategy": strategy,
                "rationale": rationale,
                "projected_margin": round(projected_margin, 4),
                "competitive_position": competitive_position,
                "confidence": confidence,
                "model_note": "Qwen: structured pricing plan and recommendation synthesis",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendation": {},
            "error": f"Price recommendation failed: {exc}",
        }


def _determine_position(our_price: float, avg_price: float) -> str:
    """Classify our price relative to market average."""
    if avg_price <= 0:
        return "unknown"

    ratio = our_price / avg_price

    if ratio < 0.85:
        return "undercut"
    if ratio < 0.95:
        return "below_market"
    if ratio < 1.05:
        return "at_market"
    if ratio < 1.15:
        return "above_market"
    return "premium"


def _margin_health_to_confidence(health: str) -> float:
    """Convert margin health label to a confidence score."""
    mapping = {
        "excellent": 0.95,
        "healthy": 0.85,
        "below_target": 0.60,
        "poor": 0.35,
        "negative": 0.10,
        "critical": 0.05,
        "overpriced": 0.30,
    }
    return mapping.get(health, 0.50)


def _build_rationale(
    optimal_price: float,
    strategy: str,
    projected_margin: float,
    target_margin: float,
    competitive_position: str,
    psychology_technique: str,
    sensitivity: str,
    cost_floor: float,
    ceiling: float,
) -> str:
    """Build a human-readable rationale for the recommended price."""
    parts: list[str] = []

    # Strategy rationale
    strategy_labels = {
        "cost_plus": "cost-plus markup ensuring target margin coverage",
        "competitive": "competitive positioning aligned with market pricing",
        "value_based": "value-based pricing reflecting customer willingness to pay",
    }
    parts.append(
        f"Recommended ${optimal_price:.2f} using {strategy_labels.get(strategy, strategy)} strategy."
    )

    # Margin commentary
    margin_pct = projected_margin * 100
    target_pct = target_margin * 100
    if projected_margin >= target_margin:
        parts.append(
            f"Projected margin of {margin_pct:.1f}% exceeds the {target_pct:.1f}% target."
        )
    else:
        parts.append(
            f"Projected margin of {margin_pct:.1f}% is below the {target_pct:.1f}% target; "
            f"consider cost reduction or repositioning."
        )

    # Competitive position
    position_labels = {
        "undercut": "significantly below competitors",
        "below_market": "slightly below market average",
        "at_market": "aligned with market average",
        "above_market": "slightly above market average",
        "premium": "positioned as a premium offering",
    }
    parts.append(
        f"Price is {position_labels.get(competitive_position, competitive_position)}."
    )

    # Psychology
    if psychology_technique != "none":
        parts.append(
            f"Applied {psychology_technique.replace('_', ' ')} for conversion optimization."
        )

    # Elasticity
    parts.append(f"Price sensitivity is {sensitivity}.")

    # Range
    parts.append(f"Viable price range: ${cost_floor:.2f} (floor) to ${ceiling:.2f} (ceiling).")

    return " ".join(parts)
