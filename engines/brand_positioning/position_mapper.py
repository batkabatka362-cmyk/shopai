"""Brand Positioning Engine — position mapper.

Maps brand and competitors on a price/quality grid,
assigning quadrant positions for strategic analysis.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Price and quality scoring
# ---------------------------------------------------------------------------

_PRICE_SCORES: dict[str, float] = {
    "budget": 1.0,
    "low": 2.0,
    "economy": 2.0,
    "mid": 5.0,
    "medium": 5.0,
    "moderate": 5.0,
    "mid-range": 5.0,
    "high": 8.0,
    "premium": 9.0,
    "luxury": 10.0,
}

_QUALITY_SCORES: dict[str, float] = {
    "low": 2.0,
    "basic": 3.0,
    "average": 5.0,
    "medium": 5.0,
    "good": 6.0,
    "high": 8.0,
    "premium": 9.0,
    "excellent": 9.0,
    "superior": 10.0,
    "luxury": 10.0,
}


def _score_attribute(value: str, score_map: dict[str, float]) -> float:
    """Convert a text attribute to a numeric score."""
    val_lower = value.lower().strip()
    for key, score in score_map.items():
        if key in val_lower:
            return score
    return 5.0  # Default mid-range


def _get_quadrant(price_score: float, quality_score: float) -> str:
    """Determine quadrant from price and quality scores."""
    if price_score >= 5.0 and quality_score >= 5.0:
        return "Premium (High Price, High Quality)"
    elif price_score < 5.0 and quality_score >= 5.0:
        return "Value (Low Price, High Quality)"
    elif price_score >= 5.0 and quality_score < 5.0:
        return "Overpriced (High Price, Low Quality)"
    else:
        return "Economy (Low Price, Low Quality)"


def map_positions(
    brand: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map brand and competitors on price/quality grid.

    Args:
        brand: Brand info dict with price_range and quality.
        competitors: List of competitor dicts.

    Returns:
        Structured dict with position map.
    """
    try:
        entries: list[dict[str, Any]] = []

        # Map the brand
        brand_price = _score_attribute(
            str(brand.get("price_range", "mid")), _PRICE_SCORES,
        )
        brand_quality = _score_attribute(
            str(brand.get("quality", "good")), _QUALITY_SCORES,
        )
        brand_quadrant = _get_quadrant(brand_price, brand_quality)

        entries.append({
            "name": str(brand.get("name", "Our Brand")),
            "price_score": brand_price,
            "quality_score": brand_quality,
            "quadrant": brand_quadrant,
        })

        # Map competitors
        for comp in competitors:
            comp_price = _score_attribute(
                str(comp.get("price_range", "mid")), _PRICE_SCORES,
            )
            comp_quality = _score_attribute(
                str(comp.get("quality", "average")), _QUALITY_SCORES,
            )
            entries.append({
                "name": str(comp.get("name", "Competitor")),
                "price_score": comp_price,
                "quality_score": comp_quality,
                "quadrant": _get_quadrant(comp_price, comp_quality),
            })

        return {
            "status": "success",
            "position_map": {
                "entries": entries,
                "brand_quadrant": brand_quadrant,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "position_map": {},
            "error": f"Position mapping failed: {exc}",
        }
