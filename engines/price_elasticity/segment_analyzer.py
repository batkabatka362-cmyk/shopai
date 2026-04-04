"""Price Elasticity Engine — segment analyzer.

Analyzes price elasticity by product segment/category to identify
which segments are most/least price-sensitive.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_segments(
    products: list[dict[str, Any]],
    sensitivities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze elasticity by segment.

    Args:
        products: List of product dicts.
        sensitivities: Per-product sensitivity results.

    Returns:
        Structured dict with per-product segment analyses.
    """
    try:
        sens_map = {str(s.get("product_id", "")): s for s in sensitivities}

        # Group by category
        category_elasticities: dict[str, list[float]] = {}
        product_categories: dict[str, str] = {}

        for item in products:
            pid = str(item.get("id", "unknown"))
            category = str(item.get("category", "general"))
            product_categories[pid] = category

            sens = sens_map.get(pid, {})
            coeff = float(sens.get("elasticity_coefficient", 0.0))

            category_elasticities.setdefault(category, []).append(coeff)

        # Compute category-level elasticity
        category_avg: dict[str, float] = {}
        for cat, coeffs in category_elasticities.items():
            if coeffs:
                category_avg[cat] = round(sum(coeffs) / len(coeffs), 3)

        # Classify segments
        segment_results: list[dict[str, Any]] = []
        for item in products:
            pid = str(item.get("id", "unknown"))
            category = product_categories.get(pid, "general")
            avg_elast = category_avg.get(category, 0.0)

            if abs(avg_elast) < 0.5:
                segment = "price_insensitive"
            elif abs(avg_elast) < 1.0:
                segment = "moderately_sensitive"
            elif abs(avg_elast) < 2.0:
                segment = "price_sensitive"
            else:
                segment = "highly_sensitive"

            segment_results.append({
                "product_id": pid,
                "segment": segment,
                "segment_elasticity": avg_elast,
            })

        return {"status": "success", "segments": segment_results}
    except Exception as exc:
        return {"status": "error", "segments": [], "error": f"Segment analysis failed: {exc}"}
