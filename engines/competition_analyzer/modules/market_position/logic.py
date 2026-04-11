"""Market position decision logic — recommendation, conflict detection, and effort estimation.

Decides:
  - What position should we take in the market?
  - Does the new position conflict with our current catalog?
  - How much effort is needed to move from one position to another?
"""
from __future__ import annotations

from typing import Any

from .data import POSITIONING_ARCHETYPES, get_archetype


POSITION_ORDER = ["budget_leader", "value_leader", "premium", "ultra_premium", "niche_specialist"]


def recommend_positioning(
    landscape: dict[str, Any], our_product: dict[str, Any]
) -> dict[str, Any]:
    """Recommend the best market position given the competitive landscape.

    Evaluates each position type and scores it based on:
      - How crowded the position is (fewer competitors = better)
      - How well our product fits (price/quality alignment)
      - The profitability potential of the position

    Args:
        landscape: Output from landscape mapping with entries and distribution.
        our_product: Our product data with price, quality_score, strengths.

    Returns:
        Dict with recommended position, confidence, reasoning, and alternatives.
    """
    distribution = landscape.get("position_distribution", {})
    our_price = our_product.get("price", 0)
    our_quality = our_product.get("quality_score", 50)
    avg_price = landscape.get("avg_price", 1)
    strengths = our_product.get("strengths", [])

    candidates = []
    for position in POSITION_ORDER:
        archetype = get_archetype(position)
        crowding = distribution.get(position, 0)
        fit = _compute_fit(position, our_price, our_quality, avg_price, strengths)

        # Empty positions get a bonus
        vacancy_bonus = 25 if crowding == 0 else max(0, 15 - crowding * 5)

        # Profitability potential from archetype
        margin_potential = archetype.get("typical_margin_pct", 30)
        margin_score = min(30, margin_potential * 0.5)

        total = fit + vacancy_bonus + margin_score
        candidates.append({
            "position": position,
            "score": round(total, 1),
            "fit": round(fit, 1),
            "vacancy_bonus": vacancy_bonus,
            "margin_score": round(margin_score, 1),
            "crowding": crowding,
            "archetype": archetype,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]
    alternatives = candidates[1:3]

    confidence = min(95, max(20, round(best["score"])))

    return {
        "position": best["position"],
        "confidence": confidence,
        "score": best["score"],
        "reasoning": _build_reasoning(best, landscape),
        "alternatives": [
            {"position": a["position"], "score": a["score"]} for a in alternatives
        ],
        "archetype": best["archetype"],
    }


def detect_positioning_conflicts(
    catalog: list[dict[str, Any]], new_position: str
) -> list[dict[str, Any]]:
    """Detect conflicts between existing catalog items and the proposed position.

    A catalog with budget products conflicts with premium positioning.
    Position must be consistent across the catalog to avoid brand confusion.

    Args:
        catalog: List of existing products with price, quality_score, position.
        new_position: The proposed new position.

    Returns:
        List of conflict dicts describing each inconsistency.
    """
    conflicts = []
    incompatible_pairs = {
        "budget_leader": {"premium", "ultra_premium"},
        "value_leader": {"ultra_premium"},
        "premium": {"budget_leader"},
        "ultra_premium": {"budget_leader", "value_leader"},
        "niche_specialist": set(),  # Niche can coexist with most positions
    }

    bad_positions = incompatible_pairs.get(new_position, set())

    for item in catalog:
        item_position = item.get("position", "")
        item_name = item.get("name", "Unknown Product")

        if item_position in bad_positions:
            conflicts.append({
                "product": item_name,
                "current_position": item_position,
                "proposed_position": new_position,
                "conflict_type": "position_mismatch",
                "severity": "high",
                "resolution": (
                    f"'{item_name}' is positioned as '{item_position}' which conflicts "
                    f"with '{new_position}'. Either reposition the product or adjust "
                    f"the overall strategy."
                ),
            })

        # Price inconsistency check
        item_price = item.get("price", 0)
        if new_position == "premium" and item_price < 20:
            conflicts.append({
                "product": item_name,
                "current_position": item_position,
                "proposed_position": new_position,
                "conflict_type": "price_inconsistency",
                "severity": "medium",
                "resolution": (
                    f"'{item_name}' priced at ${item_price} undermines premium positioning. "
                    f"Consider removing or repricing."
                ),
            })

    return conflicts


def estimate_repositioning_effort(
    from_pos: str, to_pos: str
) -> dict[str, Any]:
    """Estimate the effort required to move from one market position to another.

    Repositioning is not just changing price — it requires changes to brand
    perception, content, packaging, service level, and customer expectations.

    Args:
        from_pos: Current position (e.g., 'budget_leader').
        to_pos: Target position (e.g., 'premium').

    Returns:
        Dict with effort_level, time_months, cost_estimate, and action plan.
    """
    # Distance between positions determines base effort
    if from_pos not in POSITION_ORDER or to_pos not in POSITION_ORDER:
        distance = 2  # Default moderate distance for niche
    else:
        from_idx = POSITION_ORDER.index(from_pos)
        to_idx = POSITION_ORDER.index(to_pos)
        distance = abs(to_idx - from_idx)

    going_up = _is_moving_up(from_pos, to_pos)

    # Effort scales with distance and direction
    base_months = distance * 3
    if going_up:
        base_months = round(base_months * 1.5)  # Moving upmarket is harder

    cost_per_month = 2000 if going_up else 1000
    total_cost = base_months * cost_per_month

    if distance <= 1:
        effort_level = "low"
    elif distance <= 2:
        effort_level = "medium"
    else:
        effort_level = "high"

    actions = _repositioning_actions(from_pos, to_pos, going_up)

    return {
        "from_position": from_pos,
        "to_position": to_pos,
        "effort_level": effort_level,
        "time_months": base_months,
        "cost_estimate_usd": total_cost,
        "direction": "upmarket" if going_up else "downmarket",
        "distance": distance,
        "actions": actions,
        "warning": (
            "Repositioning risks losing existing customers who chose you for "
            "your current position. Plan transition carefully."
        ),
    }


def _compute_fit(
    position: str,
    our_price: float,
    our_quality: float,
    avg_price: float,
    strengths: list[str],
) -> float:
    """Compute how well our product fits a given position."""
    price_ratio = our_price / avg_price if avg_price > 0 else 1.0

    fit_scores = {
        "budget_leader": 40 if price_ratio < 0.7 else 20 if price_ratio < 0.9 else 5,
        "value_leader": 40 if 0.7 <= price_ratio <= 1.0 and our_quality >= 55 else 15,
        "premium": 40 if price_ratio >= 1.1 and our_quality >= 70 else 10,
        "ultra_premium": 40 if price_ratio >= 1.4 and our_quality >= 85 else 5,
        "niche_specialist": 35 if our_quality >= 65 else 15,
    }

    base = fit_scores.get(position, 20)

    # Strength bonuses
    strength_keywords = {
        "budget_leader": ["cheap", "affordable", "value", "bulk"],
        "value_leader": ["quality", "value", "reliable", "durable"],
        "premium": ["premium", "luxury", "crafted", "exclusive"],
        "ultra_premium": ["luxury", "bespoke", "artisan", "elite"],
        "niche_specialist": ["specialized", "expert", "niche", "unique"],
    }
    keywords = strength_keywords.get(position, [])
    strength_match = sum(
        1 for s in strengths if any(kw in s.lower() for kw in keywords)
    )
    base += min(15, strength_match * 5)

    return base


def _is_moving_up(from_pos: str, to_pos: str) -> bool:
    """Determine if repositioning is moving upmarket."""
    tier = {"budget_leader": 1, "value_leader": 2, "premium": 3, "ultra_premium": 4, "niche_specialist": 3}
    return tier.get(to_pos, 2) > tier.get(from_pos, 2)


def _repositioning_actions(from_pos: str, to_pos: str, going_up: bool) -> list[str]:
    """Generate specific actions needed for repositioning."""
    actions = []

    if going_up:
        actions.extend([
            "Upgrade product quality and packaging to match new tier",
            "Invest in professional photography and premium listing content",
            "Gradually increase prices over 2-3 months (avoid shock)",
            "Add premium service touches (faster shipping, better support)",
            "Update brand messaging to reflect new positioning",
        ])
    else:
        actions.extend([
            "Streamline product to reduce costs while maintaining core quality",
            "Simplify packaging to reduce per-unit cost",
            "Adjust pricing to be competitive in the new tier",
            "Focus messaging on value and affordability",
            "Increase inventory to support higher volume at lower margins",
        ])

    if to_pos == "niche_specialist":
        actions.append("Identify and deeply serve one specific sub-segment")
        actions.append("Create specialized content for the target niche audience")

    return actions


def _build_reasoning(best: dict[str, Any], landscape: dict[str, Any]) -> str:
    """Build a human-readable explanation for the recommendation."""
    position = best["position"]
    crowding = best["crowding"]
    fit = best["fit"]

    parts = [f"Recommended position: '{position}'."]

    if crowding == 0:
        parts.append("This position is currently unoccupied — first-mover advantage.")
    elif crowding <= 2:
        parts.append(f"Only {crowding} competitor(s) in this position — room to compete.")
    else:
        parts.append(f"{crowding} competitors here, but strong product fit justifies entry.")

    if fit >= 35:
        parts.append("Your product naturally aligns well with this positioning.")
    else:
        parts.append("Some product adjustments may be needed to fully own this position.")

    return " ".join(parts)
