"""Market Research Engine — gap analyzer.

Analyze market gaps by comparing competitor offerings against demand signals.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_gaps(
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze market gaps.

    Args:
        **kwargs: Must include competitors, search_data, size data.

    Returns:
        Structured dict with identified market gaps.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        search_data = kwargs.get("search_data", {})
        size_data = kwargs.get("size_estimator_data", {})

        # Analyze price gaps
        prices = [float(c.get("avg_price", 0)) for c in competitors if c.get("avg_price")]
        gaps: list[dict[str, Any]] = []

        if prices:
            min_price = min(prices)
            max_price = max(prices)
            avg_price = sum(prices) / len(prices)

            # Price gap: if big spread, there might be an underserved segment
            if max_price > min_price * 2:
                gaps.append({
                    "type": "price",
                    "description": f"Wide price range (${min_price:.0f}-${max_price:.0f}) suggests underserved segments",
                    "opportunity": "mid_market" if avg_price > min_price * 1.5 else "premium",
                })

        # Feature gaps from search data
        unmet_keywords = search_data.get("unmet_demand_keywords", [])
        for kw in unmet_keywords:
            gaps.append({
                "type": "feature",
                "description": f"Unmet demand for: {kw}",
                "opportunity": "product_development",
            })

        # Geography gaps
        underserved_regions = search_data.get("underserved_regions", [])
        for region in underserved_regions:
            gaps.append({
                "type": "geography",
                "description": f"Underserved region: {region}",
                "opportunity": "geographic_expansion",
            })

        return {
            "status": "success",
            "result": {"gaps": gaps, "total_gaps": len(gaps)},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Gap analysis failed: {exc}"}
