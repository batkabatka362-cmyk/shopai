"""Alternative Presenter — comparison and rejection logic.

Compares alternative products to the selected product dimension by
dimension, and generates clear explanations for why each alternative
was not chosen. Identifies advantages the alternative has (for
balanced reporting) and the specific weaknesses that disqualified it.
"""

from __future__ import annotations

from typing import Any

from .data import REJECTION_CATEGORIES


def compare_to_selection(
    alternative: dict[str, Any], selected: dict[str, Any],
) -> dict[str, Any]:
    """Compare an alternative product to the selected product.

    Evaluates each scoring dimension to identify where the alternative
    is stronger and where it is weaker than the selection.

    Args:
        alternative: The alternative product dict with engine scores.
        selected: The selected product dict with engine scores.

    Returns:
        Comparison dict with advantages, disadvantages, and dimension scores.
    """
    dimensions = _extract_comparison_dimensions(alternative, selected)
    advantages: list[str] = []
    disadvantages: list[str] = []
    dimension_details: list[dict[str, Any]] = []

    for dim in dimensions:
        name = dim["name"]
        alt_val = dim["alternative_value"]
        sel_val = dim["selected_value"]
        diff = alt_val - sel_val

        detail = {
            "dimension": name,
            "alternative_value": round(alt_val, 1),
            "selected_value": round(sel_val, 1),
            "difference": round(diff, 1),
            "winner": "alternative" if diff > 0 else "selected" if diff < 0 else "tie",
        }
        dimension_details.append(detail)

        if diff > 5:
            advantages.append(f"better {name} ({alt_val:.0f} vs {sel_val:.0f})")
        elif diff < -5:
            disadvantages.append(f"weaker {name} ({alt_val:.0f} vs {sel_val:.0f})")

    return {
        "alternative_advantages": advantages,
        "alternative_disadvantages": disadvantages,
        "dimension_details": dimension_details,
        "dimensions_compared": len(dimensions),
        "dimensions_won_by_alternative": len(advantages),
        "dimensions_won_by_selected": len(disadvantages),
    }


def explain_rejection_reason(
    alternative: dict[str, Any],
    selected: dict[str, Any],
    goal: str = "balanced",
) -> dict[str, Any]:
    """Explain why an alternative was not selected.

    Identifies the primary reason the alternative ranked lower, maps
    it to a rejection category, and provides a clear explanation.

    Args:
        alternative: The alternative product dict.
        selected: The selected product dict.
        goal: The optimization goal (profit|growth|balanced).

    Returns:
        Rejection explanation dict with reason, category, and details.
    """
    alt_score = alternative.get("unified_score", 0)
    sel_score = selected.get("unified_score", 0)
    score_gap = sel_score - alt_score

    # Determine the primary weakness
    primary_reason = ""
    category = "lower_overall_score"
    details: list[str] = []

    # Check each dimension for the biggest gap
    gaps = _find_biggest_gaps(alternative, selected)

    if gaps:
        worst_gap = gaps[0]
        dim_name = worst_gap["dimension"]
        gap_size = worst_gap["gap"]

        if dim_name == "margin" and gap_size > 5:
            category = "lower_profitability"
            primary_reason = (
                f"Lower profitability — margin is {gap_size:.0f} percentage "
                f"points below the selected product"
            )
        elif dim_name == "demand_score" and gap_size > 10:
            category = "lower_demand"
            primary_reason = f"Lower demand score by {gap_size:.0f} points"
        elif dim_name == "competition_score" and gap_size > 10:
            category = "worse_competition"
            primary_reason = f"More competitive market (score {gap_size:.0f} points lower)"
        elif dim_name == "risk" and gap_size > 10:
            category = "higher_risk"
            primary_reason = f"Higher risk profile by {gap_size:.0f} points"
        else:
            primary_reason = f"Weaker on {dim_name} by {gap_size:.0f} points"

    if not primary_reason:
        primary_reason = f"Lower overall score ({alt_score:.1f} vs {sel_score:.1f})"

    # Add goal-specific context
    goal_context = _goal_rejection_context(alternative, selected, goal)
    if goal_context:
        details.append(goal_context)

    # Get category info
    cat_info = REJECTION_CATEGORIES.get(category, REJECTION_CATEGORIES["lower_overall_score"])

    return {
        "primary_reason": primary_reason,
        "category": category,
        "category_description": cat_info["description"],
        "score_gap": round(score_gap, 1),
        "details": details,
        "revisit_condition": cat_info.get("revisit_condition", ""),
    }


def _extract_comparison_dimensions(
    alt: dict[str, Any], sel: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract comparable numeric dimensions from two products."""
    dimensions: list[dict[str, Any]] = []

    # Profitability
    alt_margin = (alt.get("profitability") or {}).get("margin", 0)
    sel_margin = (sel.get("profitability") or {}).get("margin", 0)
    dimensions.append({"name": "margin", "alternative_value": alt_margin, "selected_value": sel_margin})

    # Demand
    alt_demand = (alt.get("demand") or {}).get("demand_score", 0)
    sel_demand = (sel.get("demand") or {}).get("demand_score", 0)
    dimensions.append({"name": "demand_score", "alternative_value": alt_demand, "selected_value": sel_demand})

    # Competition
    alt_comp = (alt.get("competition") or {}).get("competition_score", 0)
    sel_comp = (sel.get("competition") or {}).get("competition_score", 0)
    dimensions.append({"name": "competition_score", "alternative_value": alt_comp, "selected_value": sel_comp})

    # Risk (lower is better, so we invert for comparison)
    alt_risk = (alt.get("risk") or {}).get("composite_risk", 50)
    sel_risk = (sel.get("risk") or {}).get("composite_risk", 50)
    dimensions.append({"name": "risk", "alternative_value": 100 - alt_risk, "selected_value": 100 - sel_risk})

    # Trend
    alt_trend = (alt.get("trend_discovery") or {}).get("trend_score", 0)
    sel_trend = (sel.get("trend_discovery") or {}).get("trend_score", 0)
    dimensions.append({"name": "trend_score", "alternative_value": alt_trend, "selected_value": sel_trend})

    return dimensions


def _find_biggest_gaps(
    alt: dict[str, Any], sel: dict[str, Any],
) -> list[dict[str, Any]]:
    """Find dimensions where the alternative is weakest compared to selection."""
    dims = _extract_comparison_dimensions(alt, sel)
    gaps: list[dict[str, Any]] = []
    for dim in dims:
        gap = dim["selected_value"] - dim["alternative_value"]
        if gap > 0:
            gaps.append({"dimension": dim["name"], "gap": gap})
    gaps.sort(key=lambda g: g["gap"], reverse=True)
    return gaps


def _goal_rejection_context(
    alt: dict[str, Any], sel: dict[str, Any], goal: str,
) -> str:
    """Add goal-specific context to the rejection explanation."""
    if goal == "profit":
        alt_margin = (alt.get("profitability") or {}).get("margin", 0)
        sel_margin = (sel.get("profitability") or {}).get("margin", 0)
        if sel_margin > alt_margin:
            return (
                f"For a profit-focused strategy, the selected product's "
                f"{sel_margin:.1f}% margin outweighs this alternative's "
                f"{alt_margin:.1f}%."
            )
    elif goal == "growth":
        alt_demand = (alt.get("demand") or {}).get("demand_score", 0)
        sel_demand = (sel.get("demand") or {}).get("demand_score", 0)
        if sel_demand > alt_demand:
            return (
                f"For a growth-focused strategy, the selected product's demand "
                f"score of {sel_demand:.0f} significantly outperforms this "
                f"alternative's {alt_demand:.0f}."
            )
    return ""
