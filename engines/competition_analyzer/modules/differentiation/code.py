"""
Differentiation — Main Entry Point
====================================
Analyzes gaps between our product and competitors across five dimensions,
scores differentiation opportunities, identifies unique selling propositions,
and recommends defensible strategies.
"""
from __future__ import annotations

from typing import Any

from .rules import evaluate_rules
from .data import STRATEGY_TEMPLATES, get_strategy_template
from .logic import (
    rank_differentiation_strategies,
    estimate_differentiation_cost,
    assess_sustainability,
)


GAP_DIMENSIONS = ["features", "service", "brand", "content", "price"]

IMPACT_LEVELS = {"high": 3, "medium": 2, "low": 1}


def find_differentiation(input_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Main engine contract function. Accepts an input payload describing
    our product and competitors, returns differentiation analysis.

    Returns dict with keys: status, data, meta, error.
    """
    try:
        product_category = input_payload.get("product_category")
        competitors = input_payload.get("competitors", [])
        our_product = input_payload.get("our_product", {})
        budget = input_payload.get("budget", "medium")
        timeline_months = input_payload.get("timeline_months", 6)

        if not product_category or not competitors or not our_product:
            return _error_response(
                "Missing required fields: product_category, competitors, our_product"
            )

        # Step 1: Analyze gaps across all dimensions
        gaps = _analyze_all_gaps(our_product, competitors)

        # Step 2: Score each gap as a differentiation opportunity
        opportunities = _score_opportunities(gaps, budget, timeline_months)

        # Step 3: Identify USPs competitors do not have
        usps = _identify_usps(our_product, competitors)

        # Step 4: Generate strategy recommendations
        strategies = _generate_strategies(opportunities, our_product, budget)
        ranked = rank_differentiation_strategies(strategies)

        # Step 5: Validate strategies against rules
        validated = []
        for strategy in ranked:
            rule_result = evaluate_rules(strategy)
            strategy["rule_check"] = rule_result
            if rule_result["passed"]:
                validated.append(strategy)

        overall_score = _compute_overall_score(gaps, usps, validated)

        return {
            "status": "success",
            "data": {
                "gaps": gaps,
                "opportunities": opportunities,
                "recommended_strategies": validated[:5],
                "all_strategies_evaluated": len(ranked),
                "usps": usps,
                "overall_differentiation_score": overall_score,
            },
            "meta": {
                "module": "differentiation",
                "version": "1.0.0",
                "competitors_analyzed": len(competitors),
                "dimensions_analyzed": GAP_DIMENSIONS,
                "budget": budget,
                "timeline_months": timeline_months,
            },
            "error": None,
        }
    except Exception as exc:
        return _error_response(f"Unexpected error: {str(exc)}")


def _error_response(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "differentiation", "version": "1.0.0"},
        "error": message,
    }


def _analyze_all_gaps(
    our_product: dict[str, Any], competitors: list[dict[str, Any]]
) -> dict[str, Any]:
    """Analyze gaps across all five dimensions."""
    gaps = {}
    for dimension in GAP_DIMENSIONS:
        gaps[dimension] = _analyze_single_gap(dimension, our_product, competitors)
    return gaps


def _analyze_single_gap(
    dimension: str,
    our_product: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the gap for a single dimension."""
    our_value = our_product.get(dimension, {})
    comp_values = [c.get(dimension, {}) for c in competitors]

    our_score = _dimension_score(dimension, our_value)
    comp_scores = [_dimension_score(dimension, cv) for cv in comp_values]
    avg_comp = sum(comp_scores) / len(comp_scores) if comp_scores else 0
    best_comp = max(comp_scores) if comp_scores else 0

    gap_vs_avg = round(our_score - avg_comp, 2)
    gap_vs_best = round(our_score - best_comp, 2)

    return {
        "dimension": dimension,
        "our_score": our_score,
        "competitor_avg": round(avg_comp, 2),
        "competitor_best": round(best_comp, 2),
        "gap_vs_avg": gap_vs_avg,
        "gap_vs_best": gap_vs_best,
        "position": "ahead" if gap_vs_avg > 0 else "behind" if gap_vs_avg < 0 else "even",
    }


def _dimension_score(dimension: str, value: Any) -> float:
    """Score a dimension value on 0-100 scale."""
    if isinstance(value, (int, float)):
        return min(100.0, max(0.0, float(value)))
    if isinstance(value, dict):
        score = value.get("score", 50)
        return min(100.0, max(0.0, float(score)))
    return 50.0


def _score_opportunities(
    gaps: dict[str, Any], budget: str, timeline_months: int
) -> list[dict[str, Any]]:
    """Score each gap as a differentiation opportunity."""
    budget_multiplier = {"low": 0.7, "medium": 1.0, "high": 1.3}.get(budget, 1.0)
    opportunities = []

    for dimension, gap_data in gaps.items():
        gap_vs_best = gap_data.get("gap_vs_best", 0)
        if gap_vs_best >= 0:
            impact = "low"
        elif gap_vs_best >= -20:
            impact = "medium"
        else:
            impact = "high"

        cost = estimate_differentiation_cost(dimension, impact)
        time_needed = cost.get("time_months", 3)
        feasible_in_timeline = time_needed <= timeline_months

        opp_score = IMPACT_LEVELS[impact] * 30 * budget_multiplier
        if feasible_in_timeline:
            opp_score *= 1.2

        opportunities.append({
            "dimension": dimension,
            "impact": impact,
            "cost_estimate": cost,
            "time_months": time_needed,
            "feasible_in_timeline": feasible_in_timeline,
            "opportunity_score": round(min(100, opp_score), 1),
        })

    opportunities.sort(key=lambda o: o["opportunity_score"], reverse=True)
    return opportunities


def _identify_usps(
    our_product: dict[str, Any], competitors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Identify unique selling propositions competitors lack."""
    our_features = set(our_product.get("unique_features", []))
    comp_features: set[str] = set()
    for comp in competitors:
        comp_features.update(comp.get("unique_features", []))

    truly_unique = our_features - comp_features
    usps = []
    for feature in truly_unique:
        usps.append({
            "feature": feature,
            "uniqueness": "exclusive",
            "communicable": len(feature.split()) <= 10,
            "recommendation": f"Lead with '{feature}' in listing title and bullets",
        })

    existing_strengths = our_product.get("strengths", [])
    for strength in existing_strengths:
        if strength not in [u["feature"] for u in usps]:
            usps.append({
                "feature": strength,
                "uniqueness": "advantage",
                "communicable": len(strength.split()) <= 10,
                "recommendation": f"Emphasize '{strength}' as a key differentiator",
            })

    return usps


def _generate_strategies(
    opportunities: list[dict[str, Any]],
    our_product: dict[str, Any],
    budget: str,
) -> list[dict[str, Any]]:
    """Generate differentiation strategies from opportunities."""
    strategy_types = [
        "better_quality", "better_service", "niche_focus",
        "brand_story", "bundling", "customization",
    ]
    strategies = []

    for stype in strategy_types:
        template = get_strategy_template(stype)
        sustainability = assess_sustainability(stype)

        cost_level = template.get("cost_level", "medium")
        budget_fits = _budget_fits(budget, cost_level)

        top_opp = opportunities[0] if opportunities else {}
        relevance = _strategy_relevance(stype, top_opp.get("dimension", ""))

        score = relevance * 40 + sustainability.get("months_defensible", 6) * 2
        if budget_fits:
            score *= 1.2

        strategies.append({
            "strategy_type": stype,
            "name": template.get("name", stype),
            "description": template.get("description", ""),
            "cost_level": cost_level,
            "budget_fits": budget_fits,
            "sustainability": sustainability,
            "relevance_score": round(min(100, score), 1),
            "actions": template.get("actions", []),
        })

    return strategies


def _budget_fits(budget: str, cost_level: str) -> bool:
    """Check if budget can cover the cost level."""
    levels = {"low": 1, "medium": 2, "high": 3}
    return levels.get(budget, 2) >= levels.get(cost_level, 2)


def _strategy_relevance(strategy_type: str, top_dimension: str) -> float:
    """How relevant is a strategy type to the biggest opportunity dimension."""
    relevance_map = {
        ("better_quality", "features"): 0.9,
        ("better_quality", "price"): 0.4,
        ("better_service", "service"): 0.95,
        ("niche_focus", "content"): 0.7,
        ("niche_focus", "brand"): 0.8,
        ("brand_story", "brand"): 0.95,
        ("brand_story", "content"): 0.8,
        ("bundling", "features"): 0.7,
        ("bundling", "price"): 0.8,
        ("customization", "features"): 0.85,
        ("customization", "service"): 0.7,
    }
    return relevance_map.get((strategy_type, top_dimension), 0.5)


def _compute_overall_score(
    gaps: dict[str, Any],
    usps: list[dict[str, Any]],
    validated_strategies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute an overall differentiation score."""
    ahead_count = sum(1 for g in gaps.values() if g.get("position") == "ahead")
    behind_count = sum(1 for g in gaps.values() if g.get("position") == "behind")
    usp_count = len([u for u in usps if u.get("uniqueness") == "exclusive"])
    strategy_count = len(validated_strategies)

    raw_score = (ahead_count * 20) + (usp_count * 15) + (strategy_count * 10) - (behind_count * 10)
    clamped = max(0, min(100, raw_score))

    if clamped >= 70:
        label = "strongly differentiated"
    elif clamped >= 40:
        label = "moderately differentiated"
    else:
        label = "weakly differentiated"

    return {
        "score": clamped,
        "label": label,
        "dimensions_ahead": ahead_count,
        "dimensions_behind": behind_count,
        "exclusive_usps": usp_count,
        "viable_strategies": strategy_count,
    }
