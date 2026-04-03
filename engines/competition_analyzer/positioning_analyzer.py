"""Competition Analyzer Engine — positioning analyzer.

Analyze market positioning of competitors: premium vs budget, niche vs mass.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_positioning(
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze market positioning of each competitor.

    Args:
        **kwargs: Must include competitors and price comparison data.

    Returns:
        Structured dict with positioning analysis.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        price_data = kwargs.get("price_comparator_data", {})
        comparisons = price_data.get("comparisons", [])

        # Build avg price diff per competitor
        comp_diffs: dict[str, list[float]] = {}
        for c in comparisons:
            cid = c["competitor_id"]
            comp_diffs.setdefault(cid, []).append(c["difference_pct"])

        positions: list[dict[str, Any]] = []
        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            diffs = comp_diffs.get(cid, [])
            avg_diff = sum(diffs) / max(len(diffs), 1) if diffs else 0

            # Positioning based on price strategy
            if avg_diff > 15:
                tier = "budget"
            elif avg_diff > 0:
                tier = "value"
            elif avg_diff > -15:
                tier = "competitive"
            else:
                tier = "premium"

            product_range = comp.get("product_count", 0)
            market_type = "mass_market" if product_range > 100 else "niche" if product_range < 20 else "mid_market"

            positions.append({
                "competitor_id": cid,
                "name": comp.get("name", ""),
                "price_tier": tier,
                "market_type": market_type,
                "avg_price_diff_pct": round(avg_diff, 1),
                "product_range": product_range,
            })

        return {
            "status": "success",
            "result": {"positions": positions},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Positioning analysis failed: {exc}"}
