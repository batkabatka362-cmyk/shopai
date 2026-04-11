"""Competition Analyzer Engine — strength mapper.

Map competitor strengths and weaknesses based on available data.
"""
from __future__ import annotations

import copy
from typing import Any


def map_strengths(
    **kwargs: Any,
) -> dict[str, Any]:
    """Map competitor strengths and weaknesses.

    Args:
        **kwargs: Must include competitors, price, and positioning data.

    Returns:
        Structured dict with strength/weakness mapping.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        price_data = kwargs.get("price_comparator_data", {})
        pos_data = kwargs.get("positioning_analyzer_data", {})
        positions = pos_data.get("positions", [])
        pos_map = {p["competitor_id"]: p for p in positions}

        mappings: list[dict[str, Any]] = []

        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            pos = pos_map.get(cid, {})
            strengths: list[str] = []
            weaknesses: list[str] = []

            # Price-based
            avg_diff = pos.get("avg_price_diff_pct", 0)
            if avg_diff > 10:
                strengths.append("Aggressive pricing undercuts market")
            elif avg_diff < -10:
                weaknesses.append("Premium pricing limits market share")

            # Range-based
            product_range = pos.get("product_range", 0)
            if product_range > 100:
                strengths.append("Wide product range")
            elif product_range < 10:
                weaknesses.append("Limited product range")

            # Rating-based
            rating = float(comp.get("avg_rating", 0))
            if rating >= 4.5:
                strengths.append("Excellent customer reviews")
            elif rating < 3.0:
                weaknesses.append("Poor customer reviews")

            # Market presence
            if comp.get("established_years", 0) > 10:
                strengths.append("Established market presence")
            elif comp.get("established_years", 0) < 2:
                weaknesses.append("New entrant, unproven track record")

            mappings.append({
                "competitor_id": cid,
                "name": comp.get("name", ""),
                "strengths": strengths if strengths else ["No clear strengths identified"],
                "weaknesses": weaknesses if weaknesses else ["No clear weaknesses identified"],
            })

        return {
            "status": "success",
            "result": {"mappings": mappings},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Strength mapping failed: {exc}"}
