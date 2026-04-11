"""Supplier scorer decision logic — comparison, recommendation, and shortlist building.

Turns raw scored suppliers into actionable decisions:
  - Head-to-head supplier comparison across all dimensions
  - Best + backup supplier recommendation from a scored list
  - Shortlist building with geographic diversity
"""
from __future__ import annotations

from typing import Any

from .data import DIMENSION_WEIGHTS, get_country_risk


def compare_suppliers(supplier_a: dict[str, Any], supplier_b: dict[str, Any]) -> dict[str, Any]:
    """Head-to-head comparison of two scored suppliers across all dimensions."""
    name_a = supplier_a.get("supplier_name", "Supplier A")
    name_b = supplier_b.get("supplier_name", "Supplier B")

    dimensions = list(DIMENSION_WEIGHTS.keys())
    advantages_a: list[str] = []
    advantages_b: list[str] = []
    dimension_results: dict[str, dict[str, Any]] = {}

    for dim in dimensions:
        score_a = supplier_a.get("dimension_scores", {}).get(dim, 0)
        score_b = supplier_b.get("dimension_scores", {}).get(dim, 0)
        weight = DIMENSION_WEIGHTS[dim]
        diff = score_a - score_b

        dimension_results[dim] = {
            name_a: score_a, name_b: score_b,
            "difference": diff, "weight": weight,
        }

        if diff > 5:
            advantages_a.append(f"Better {dim.replace('_', ' ')} ({score_a} vs {score_b})")
        elif diff < -5:
            advantages_b.append(f"Better {dim.replace('_', ' ')} ({score_b} vs {score_a})")

    comp_a = supplier_a.get("composite_score", 0)
    comp_b = supplier_b.get("composite_score", 0)
    tier_a = supplier_a.get("tier", "unverified")
    tier_b = supplier_b.get("tier", "unverified")

    if comp_a > comp_b:
        winner, margin = name_a, comp_a - comp_b
    elif comp_b > comp_a:
        winner, margin = name_b, comp_b - comp_a
    else:
        winner, margin = "tie", 0

    # Risk comparison
    flags_a = len(supplier_a.get("red_flags", []))
    flags_b = len(supplier_b.get("red_flags", []))
    if flags_a < flags_b:
        advantages_a.append(f"Fewer red flags ({flags_a} vs {flags_b})")
    elif flags_b < flags_a:
        advantages_b.append(f"Fewer red flags ({flags_b} vs {flags_a})")

    recommendation = _comparison_recommendation(winner, margin, tier_a, tier_b, name_a, name_b)

    return {
        "winner": winner,
        "margin": round(margin, 1),
        "decisive": margin > 15,
        name_a: {"composite": comp_a, "tier": tier_a, "advantages": advantages_a, "red_flags": flags_a},
        name_b: {"composite": comp_b, "tier": tier_b, "advantages": advantages_b, "red_flags": flags_b},
        "dimension_breakdown": dimension_results,
        "recommendation": recommendation,
    }


def _comparison_recommendation(winner: str, margin: float, tier_a: str, tier_b: str,
                                name_a: str, name_b: str) -> str:
    """Generate a recommendation from the comparison results."""
    if winner == "tie":
        return f"Very close — order samples from both {name_a} and {name_b} to decide on quality"
    if margin > 20:
        return f"Clear winner: {winner}. Significant advantage across multiple dimensions."
    if margin > 10:
        return f"{winner} is the better choice, but keep the other as backup."
    return f"Slight edge to {winner}. Consider ordering samples from both before committing."


def recommend_supplier(scored_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best supplier and a backup from a scored and sorted list.

    The backup supplier should ideally be from a different country for supply chain resilience.
    """
    if not scored_list:
        return {"primary": None, "backup": None, "reasoning": "No suppliers to evaluate"}

    # Sort by composite score descending
    ranked = sorted(scored_list, key=lambda s: s.get("composite_score", 0), reverse=True)

    # Filter out suppliers with blockers
    viable = [s for s in ranked if not s.get("has_blockers", False)]
    if not viable:
        return {
            "primary": None, "backup": None,
            "reasoning": "All suppliers have blocking issues — expand search or relax constraints",
        }

    primary = viable[0]
    primary_country = primary.get("country", "")

    # Find backup: prefer different country for resilience
    backup = None
    for candidate in viable[1:]:
        if candidate.get("country", "") != primary_country:
            backup = candidate
            break
    # If no different-country backup, take second best
    if backup is None and len(viable) > 1:
        backup = viable[1]

    reasoning_parts = [f"Primary: {primary.get('supplier_name', 'Unknown')} (score {primary.get('composite_score', 0)}, {primary.get('tier', 'unverified')} tier)"]
    if backup:
        reasoning_parts.append(
            f"Backup: {backup.get('supplier_name', 'Unknown')} (score {backup.get('composite_score', 0)}, "
            f"{'different country for resilience' if backup.get('country') != primary_country else 'same country'})"
        )
    else:
        reasoning_parts.append("No backup available — consider expanding supplier search")

    return {
        "primary": primary,
        "backup": backup,
        "total_viable": len(viable),
        "total_evaluated": len(scored_list),
        "reasoning": ". ".join(reasoning_parts),
    }


def build_supplier_shortlist(suppliers: list[dict[str, Any]], max_suppliers: int = 3) -> dict[str, Any]:
    """Build a shortlist of top suppliers with geographic diversity.

    Ensures not all selected suppliers are from the same country,
    balancing quality scores with supply chain resilience.
    """
    if not suppliers:
        return {"shortlist": [], "total_candidates": 0, "strategy": "No suppliers to shortlist"}

    ranked = sorted(suppliers, key=lambda s: s.get("composite_score", 0), reverse=True)
    viable = [s for s in ranked if not s.get("has_blockers", False)]

    selected: list[dict[str, Any]] = []
    countries_used: dict[str, int] = {}
    max_same_country = max(1, max_suppliers - 1)  # At least one slot reserved for diversity

    # First pass: greedy selection with diversity constraint
    for supplier in viable:
        if len(selected) >= max_suppliers:
            break
        country = supplier.get("country", "unknown")
        if countries_used.get(country, 0) >= max_same_country:
            continue
        selected.append(supplier)
        countries_used[country] = countries_used.get(country, 0) + 1

    # Second pass: fill remaining slots if diversity prevented filling
    if len(selected) < max_suppliers:
        for supplier in viable:
            if len(selected) >= max_suppliers:
                break
            if supplier not in selected:
                selected.append(supplier)
                country = supplier.get("country", "unknown")
                countries_used[country] = countries_used.get(country, 0) + 1

    # Enrich with position and country risk
    for i, supplier in enumerate(selected):
        supplier["shortlist_rank"] = i + 1
        country = supplier.get("country", "")
        risk = get_country_risk(country)
        supplier["country_risk_score"] = risk["score"]
        supplier["country_risk_notes"] = risk["notes"]

    diversified = len(countries_used) > 1
    avg_score = round(sum(s.get("composite_score", 0) for s in selected) / len(selected), 1) if selected else 0

    return {
        "shortlist": selected,
        "total_candidates": len(suppliers),
        "total_viable": len(viable),
        "countries_represented": list(countries_used.keys()),
        "diversified": diversified,
        "average_score": avg_score,
        "strategy": _shortlist_strategy(selected, diversified),
    }


def _shortlist_strategy(selected: list[dict[str, Any]], diversified: bool) -> str:
    """Generate a strategy note for the shortlist."""
    if not selected:
        return "No viable suppliers found — broaden search criteria or try alternative platforms"
    if len(selected) == 1:
        return "Only one viable supplier — high supply chain risk. Actively search for alternatives."
    if diversified:
        return "Good geographic diversity — reduces supply chain disruption risk. Order samples from all."
    return "All suppliers from same region — consider sourcing from a second country for resilience."
