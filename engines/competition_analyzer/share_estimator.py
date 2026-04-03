"""Competition Analyzer Engine — share estimator.

Estimate market share for each competitor and identify threats/opportunities.
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_share(
    **kwargs: Any,
) -> dict[str, Any]:
    """Estimate market share and identify threats/opportunities.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with share estimates, threats, opportunities.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        market_data = kwargs.get("market_data", {})
        pos_data = kwargs.get("positioning_analyzer_data", {})
        strength_data = kwargs.get("strength_mapper_data", {})

        positions = pos_data.get("positions", [])
        mappings = strength_data.get("mappings", [])
        pos_map = {p["competitor_id"]: p for p in positions}
        str_map = {m["competitor_id"]: m for m in mappings}
        total_market = float(market_data.get("total_market_size", 1000000))

        analysis: list[dict[str, Any]] = []
        threats: list[str] = []
        opportunities: list[str] = []

        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            name = comp.get("name", cid)
            pos = pos_map.get(cid, {})
            strs = str_map.get(cid, {})

            # Estimate share from available signals
            revenue = float(comp.get("estimated_revenue", 0))
            estimated_share = round(revenue / total_market * 100, 1) if revenue > 0 else 0.0

            analysis.append({
                "competitor": name,
                "pricing": pos.get("price_tier", "unknown"),
                "positioning": pos.get("market_type", "unknown"),
                "strengths": strs.get("strengths", []),
                "weaknesses": strs.get("weaknesses", []),
                "estimated_share": estimated_share,
            })

            # Threats: strong competitors gaining share
            if estimated_share > 20 and len(strs.get("strengths", [])) > len(strs.get("weaknesses", [])):
                threats.append(f"{name} holds ~{estimated_share}% share with strong positioning")

            # Opportunities: weak competitors with share to capture
            if len(strs.get("weaknesses", [])) > len(strs.get("strengths", [])):
                opportunities.append(f"{name} shows weaknesses — opportunity to capture share")

        return {
            "status": "success",
            "result": {
                "analysis": analysis,
                "threats": threats if threats else ["No significant threats identified"],
                "opportunities": opportunities if opportunities else ["Market appears stable"],
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Share estimation failed: {exc}"}
