"""Product Optimization Engine — improvement finder.

Identifies specific improvement opportunities based on performance
weaknesses and product attributes.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_WEAKNESS_IMPROVEMENTS: dict[str, dict[str, Any]] = {
    "low_conversion": {
        "type": "conversion",
        "recommendation": "Improve product listing with better images and descriptions",
        "base_impact": 0.15,
    },
    "high_returns": {
        "type": "quality",
        "recommendation": "Review product quality and set clearer expectations in listing",
        "base_impact": 0.10,
    },
    "low_rating": {
        "type": "satisfaction",
        "recommendation": "Address common customer complaints and improve product quality",
        "base_impact": 0.12,
    },
    "poor_view_to_sale": {
        "type": "listing",
        "recommendation": "Optimize listing title, pricing, and featured image for click-through",
        "base_impact": 0.08,
    },
}


def find_improvements(
    analyses: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find improvement opportunities for each product.

    Args:
        analyses: Per-product performance analyses.
        products: List of product dicts.

    Returns:
        Structured dict with per-product improvement opportunities.
    """
    try:
        improvements: list[dict[str, Any]] = []

        for analysis in analyses:
            pid = str(analysis.get("product_id", "unknown"))
            weaknesses = analysis.get("weaknesses", [])
            overall_score = float(analysis.get("overall_score", 0.5))

            for weakness in weaknesses:
                info = _WEAKNESS_IMPROVEMENTS.get(weakness)
                if not info:
                    continue

                # Scale impact by how poor the overall score is
                impact_multiplier = max(1.0 - overall_score, 0.3)
                expected_impact = round(info["base_impact"] * impact_multiplier, 3)

                if expected_impact > 0.10:
                    priority = "high"
                elif expected_impact > 0.05:
                    priority = "medium"
                else:
                    priority = "low"

                improvements.append({
                    "product_id": pid,
                    "improvement_type": info["type"],
                    "recommendation": info["recommendation"],
                    "expected_impact": expected_impact,
                    "priority": priority,
                })

        return {"status": "success", "improvements": improvements}
    except Exception as exc:
        return {"status": "error", "improvements": [], "error": f"Improvement finding failed: {exc}"}
