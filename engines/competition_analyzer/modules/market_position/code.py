"""
Market Position — Main Entry Point
====================================
Maps the competitive landscape on price-vs-quality axes, identifies empty
positions where no competitor sits, recommends optimal positioning, and
calculates a positioning fit score.
"""
from __future__ import annotations

from typing import Any

from .rules import evaluate_rules
from .data import POSITIONING_ARCHETYPES, get_archetype
from .logic import (
    recommend_positioning,
    detect_positioning_conflicts,
    estimate_repositioning_effort,
)


POSITION_TYPES = ["budget_leader", "value_leader", "premium", "ultra_premium", "niche_specialist"]


def analyze_market_position(input_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Main engine contract function. Accepts an input payload with competitor
    data and our product info, returns positioning analysis.

    Returns dict with keys: status, data, meta, error.
    """
    try:
        product_category = input_payload.get("product_category")
        competitors = input_payload.get("competitors", [])
        our_product = input_payload.get("our_product", {})
        current_position = input_payload.get("current_position")
        target_margin_pct = input_payload.get("target_margin_pct", 30)
        catalog = input_payload.get("catalog", [])

        if not product_category or not competitors or not our_product:
            return _error_response(
                "Missing required fields: product_category, competitors, our_product"
            )

        # Step 1: Map the competitive landscape (price vs quality matrix)
        landscape = _map_landscape(competitors, our_product)

        # Step 2: Identify empty positions no competitor occupies
        empty_positions = _find_empty_positions(landscape)

        # Step 3: Recommend optimal positioning
        recommendation = recommend_positioning(landscape, our_product)

        # Step 4: Check for conflicts with existing catalog
        conflicts = []
        if catalog:
            conflicts = detect_positioning_conflicts(catalog, recommendation["position"])

        # Step 5: If repositioning, estimate effort
        reposition_effort = None
        if current_position and current_position != recommendation["position"]:
            reposition_effort = estimate_repositioning_effort(
                current_position, recommendation["position"]
            )

        # Step 6: Validate against rules
        rule_context = {
            "recommended_position": recommendation["position"],
            "current_position": current_position,
            "target_margin_pct": target_margin_pct,
            "catalog": catalog,
            "conflicts": conflicts,
        }
        rule_result = evaluate_rules(rule_context)

        # Step 7: Calculate positioning fit score
        fit_score = _calculate_fit_score(
            landscape, recommendation, conflicts, our_product
        )

        return {
            "status": "success",
            "data": {
                "landscape": landscape,
                "empty_positions": empty_positions,
                "recommended_position": recommendation,
                "positioning_score": fit_score,
                "conflicts": conflicts,
                "repositioning_effort": reposition_effort,
                "rule_check": rule_result,
            },
            "meta": {
                "module": "market_position",
                "version": "1.0.0",
                "competitors_analyzed": len(competitors),
                "positions_evaluated": len(POSITION_TYPES),
                "product_category": product_category,
                "current_position": current_position,
            },
            "error": None,
        }
    except Exception as exc:
        return _error_response(f"Unexpected error: {str(exc)}")


def _error_response(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "market_position", "version": "1.0.0"},
        "error": message,
    }


def _map_landscape(
    competitors: list[dict[str, Any]], our_product: dict[str, Any]
) -> dict[str, Any]:
    """Map all competitors and our product on a price-vs-quality matrix."""
    entries = []

    for comp in competitors:
        price = comp.get("price", 0)
        quality = comp.get("quality_score", 50)
        name = comp.get("name", "Unknown")
        position = _classify_position(price, quality, competitors)

        entries.append({
            "name": name,
            "price": price,
            "quality_score": quality,
            "position": position,
            "is_ours": False,
        })

    our_price = our_product.get("price", 0)
    our_quality = our_product.get("quality_score", 50)
    our_position = _classify_position(our_price, our_quality, competitors)

    entries.append({
        "name": our_product.get("name", "Our Product"),
        "price": our_price,
        "quality_score": our_quality,
        "position": our_position,
        "is_ours": True,
    })

    # Compute landscape statistics
    prices = [e["price"] for e in entries if e["price"] > 0]
    qualities = [e["quality_score"] for e in entries]

    return {
        "entries": entries,
        "price_range": {"min": min(prices) if prices else 0, "max": max(prices) if prices else 0},
        "quality_range": {"min": min(qualities), "max": max(qualities)},
        "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
        "avg_quality": round(sum(qualities) / len(qualities), 2) if qualities else 0,
        "our_position": our_position,
        "position_distribution": _count_positions(entries),
    }


def _classify_position(
    price: float, quality: float, competitors: list[dict[str, Any]]
) -> str:
    """Classify a product's position based on price and quality relative to market."""
    comp_prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
    if not comp_prices:
        return "value_leader"

    avg_price = sum(comp_prices) / len(comp_prices)
    price_ratio = price / avg_price if avg_price > 0 else 1.0

    if price_ratio < 0.6:
        return "budget_leader"
    elif price_ratio < 0.9 and quality >= 60:
        return "value_leader"
    elif price_ratio < 1.3 and quality >= 70:
        return "premium"
    elif price_ratio >= 1.3 and quality >= 80:
        return "ultra_premium"
    elif quality >= 75 and price_ratio < 1.1:
        return "niche_specialist"
    elif price_ratio < 0.9:
        return "budget_leader"
    else:
        return "value_leader"


def _count_positions(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Count how many products sit in each position."""
    counts: dict[str, int] = {pos: 0 for pos in POSITION_TYPES}
    for entry in entries:
        pos = entry.get("position", "")
        if pos in counts:
            counts[pos] += 1
    return counts


def _find_empty_positions(landscape: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify positions where no competitor currently sits."""
    distribution = landscape.get("position_distribution", {})
    empty = []

    for position in POSITION_TYPES:
        count = distribution.get(position, 0)
        if count == 0:
            archetype = get_archetype(position)
            empty.append({
                "position": position,
                "archetype": archetype,
                "opportunity": "high" if position in ("value_leader", "niche_specialist") else "medium",
                "risk": "low" if count == 0 else "medium",
                "note": f"No competitor occupies the '{position}' position — potential opening",
            })

    return empty


def _calculate_fit_score(
    landscape: dict[str, Any],
    recommendation: dict[str, Any],
    conflicts: list[dict[str, Any]],
    our_product: dict[str, Any],
) -> dict[str, Any]:
    """Calculate how well the recommended position fits the market and our capabilities."""
    position = recommendation.get("position", "")
    confidence = recommendation.get("confidence", 50)

    # Fewer competitors in position = better fit
    distribution = landscape.get("position_distribution", {})
    crowding = distribution.get(position, 0)
    crowding_penalty = min(30, crowding * 10)

    # Conflicts reduce score
    conflict_penalty = len(conflicts) * 15

    # Our quality and price alignment with position
    alignment = _position_alignment(position, our_product, landscape)

    raw_score = confidence - crowding_penalty - conflict_penalty + alignment
    clamped = max(0, min(100, round(raw_score)))

    if clamped >= 70:
        label = "excellent fit"
    elif clamped >= 45:
        label = "moderate fit"
    else:
        label = "poor fit"

    return {
        "score": clamped,
        "label": label,
        "confidence": confidence,
        "crowding_penalty": crowding_penalty,
        "conflict_penalty": conflict_penalty,
        "alignment_bonus": alignment,
        "recommendation": (
            f"Position as '{position}' — {label}. "
            f"{'Proceed with confidence.' if clamped >= 70 else 'Consider adjustments.'}"
        ),
    }


def _position_alignment(
    position: str, our_product: dict[str, Any], landscape: dict[str, Any]
) -> float:
    """How well does our product naturally align with the target position?"""
    our_price = our_product.get("price", 0)
    our_quality = our_product.get("quality_score", 50)
    avg_price = landscape.get("avg_price", our_price)

    price_ratio = our_price / avg_price if avg_price > 0 else 1.0

    alignment_map = {
        "budget_leader": 20 if price_ratio < 0.7 else -10,
        "value_leader": 20 if 0.7 <= price_ratio <= 1.0 and our_quality >= 60 else -10,
        "premium": 20 if price_ratio >= 1.1 and our_quality >= 70 else -10,
        "ultra_premium": 20 if price_ratio >= 1.4 and our_quality >= 85 else -15,
        "niche_specialist": 15 if our_quality >= 70 else -5,
    }

    return alignment_map.get(position, 0)
