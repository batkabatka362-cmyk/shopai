"""Comparison data — dimension weights, trade-off templates, matrix formats.

Reference data for structuring head-to-head product comparisons.
Weights reflect relative importance for typical Shopify store decisions.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Dimension comparison weights (sum to 1.0)
# --------------------------------------------------------------------------- #
DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "balanced": {
        "profitability": 0.25,
        "demand": 0.25,
        "competition": 0.15,
        "risk": 0.20,
        "trend": 0.15,
    },
    "profit": {
        "profitability": 0.40,
        "demand": 0.20,
        "competition": 0.10,
        "risk": 0.20,
        "trend": 0.10,
    },
    "growth": {
        "profitability": 0.15,
        "demand": 0.35,
        "competition": 0.10,
        "risk": 0.15,
        "trend": 0.25,
    },
}

# --------------------------------------------------------------------------- #
#  Trade-off templates — common trade-off patterns in e-commerce
# --------------------------------------------------------------------------- #
TRADEOFF_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "margin_vs_demand",
        "name": "Higher margin vs. higher demand",
        "dimension_a": "profitability",
        "dimension_b": "demand",
        "description": (
            "Product A has better margins but Product B has higher demand. "
            "Higher demand can compensate for lower margins through volume."
        ),
        "resolution": "Calculate total monthly profit at projected volumes for both.",
        "threshold_gap": 15.0,
    },
    {
        "id": "risk_vs_potential",
        "name": "Lower risk vs. higher potential",
        "dimension_a": "risk",
        "dimension_b": "profitability",
        "description": (
            "Product A is safer but Product B has higher upside. "
            "Risk tolerance depends on your financial runway."
        ),
        "resolution": "Choose low-risk if runway < 3 months, high-potential if > 6 months.",
        "threshold_gap": 20.0,
    },
    {
        "id": "trend_vs_competition",
        "name": "Trending but competitive vs. stable but niche",
        "dimension_a": "trend",
        "dimension_b": "competition",
        "description": (
            "Product A rides a trend but faces heavy competition. "
            "Product B has less demand but also less competition."
        ),
        "resolution": "Trending + competitive favors speed. Niche + stable favors differentiation.",
        "threshold_gap": 20.0,
    },
    {
        "id": "demand_vs_competition",
        "name": "High demand with high competition vs. moderate demand with low competition",
        "dimension_a": "demand",
        "dimension_b": "competition",
        "description": (
            "Large market but crowded vs. smaller market with room to grow. "
            "Your marketing budget determines which is better."
        ),
        "resolution": "Big budget = big market. Small budget = find a niche.",
        "threshold_gap": 15.0,
    },
]

# --------------------------------------------------------------------------- #
#  Decision matrix format — structure for comparison output
# --------------------------------------------------------------------------- #
DECISION_MATRIX_FORMAT: dict[str, Any] = {
    "columns": ["dimension", "weight", "product_scores", "winner", "gap", "significance"],
    "significance_levels": {
        "decisive": {"min_gap": 25.0, "label": "Decisive advantage"},
        "meaningful": {"min_gap": 10.0, "label": "Meaningful advantage"},
        "marginal": {"min_gap": 3.0, "label": "Marginal advantage"},
        "negligible": {"min_gap": 0.0, "label": "No meaningful difference"},
    },
    "summary_fields": [
        "overall_winner",
        "dimensions_won",
        "critical_weaknesses",
        "trade_off_count",
    ],
}


def get_dimension_weight(goal: str, dimension: str) -> float:
    """Get the weight for a specific dimension under a given goal."""
    weights = DIMENSION_WEIGHTS.get(goal, DIMENSION_WEIGHTS["balanced"])
    return weights.get(dimension, 0.10)


def get_significance_level(gap: float) -> dict[str, Any]:
    """Classify the significance of a score gap between products."""
    for level_name in ["decisive", "meaningful", "marginal", "negligible"]:
        level = DECISION_MATRIX_FORMAT["significance_levels"][level_name]
        if gap >= level["min_gap"]:
            return {"level": level_name, "label": level["label"], "gap": gap}
    return {"level": "negligible", "label": "No meaningful difference", "gap": gap}


def get_tradeoff_template(dimension_a: str, dimension_b: str) -> dict[str, Any] | None:
    """Find a trade-off template matching two competing dimensions."""
    for template in TRADEOFF_TEMPLATES:
        dims = {template["dimension_a"], template["dimension_b"]}
        if {dimension_a, dimension_b} == dims:
            return template
    return None
