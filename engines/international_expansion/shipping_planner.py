"""International Expansion Engine — shipping planner.

Plans international shipping zones, costs, and transit times.
All calculations are real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_SHIPPING_DATA: dict[str, dict[str, Any]] = {
    "US": {"zones": ["domestic"], "cost_per_unit": 5.99, "transit_days": 3, "customs": "N/A — domestic"},
    "UK": {"zones": ["transatlantic", "EU-adjacent"], "cost_per_unit": 12.50, "transit_days": 7, "customs": "Post-Brexit customs declarations required"},
    "DE": {"zones": ["EU"], "cost_per_unit": 11.00, "transit_days": 7, "customs": "EU VAT reverse charge may apply"},
    "FR": {"zones": ["EU"], "cost_per_unit": 11.50, "transit_days": 8, "customs": "EU standard customs procedure"},
    "JP": {"zones": ["Asia-Pacific"], "cost_per_unit": 18.00, "transit_days": 10, "customs": "Japanese customs — JCT applies at import"},
    "AU": {"zones": ["Asia-Pacific", "Oceania"], "cost_per_unit": 16.50, "transit_days": 12, "customs": "GST on imported goods over AUD 1000"},
    "CA": {"zones": ["North America"], "cost_per_unit": 8.50, "transit_days": 5, "customs": "USMCA may reduce duties"},
    "KR": {"zones": ["Asia-Pacific"], "cost_per_unit": 17.00, "transit_days": 10, "customs": "Korean customs duty + VAT on CIF value"},
    "BR": {"zones": ["South America"], "cost_per_unit": 22.00, "transit_days": 15, "customs": "High import duties — ICMS + IPI + PIS/COFINS"},
    "IN": {"zones": ["South Asia"], "cost_per_unit": 19.00, "transit_days": 14, "customs": "BIS certification may be required for electronics"},
    "MX": {"zones": ["North America"], "cost_per_unit": 10.00, "transit_days": 7, "customs": "USMCA benefits for qualifying goods"},
    "SE": {"zones": ["EU", "Nordics"], "cost_per_unit": 12.00, "transit_days": 8, "customs": "EU standard — Swedish Moms (VAT) at 25%"},
}


def plan_shipping(
    target_markets: list[str],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan international shipping for target markets.

    Args:
        target_markets: List of market codes.
        products: Product list for weight/dimension considerations.

    Returns:
        Structured dict with shipping plans per market.
    """
    try:
        plans: list[dict[str, Any]] = []
        weights = [float(p.get("weight", 0.5)) for p in products]
        avg_weight = sum(weights) / len(weights) if weights else 0.5
        weight_multiplier = max(1.0, avg_weight / 0.5)

        for market in target_markets:
            code = market.upper().strip()
            ref = _SHIPPING_DATA.get(code, {
                "zones": ["international"], "cost_per_unit": 20.00,
                "transit_days": 14, "customs": "Standard international customs procedures apply",
            })

            adjusted_cost = round(ref["cost_per_unit"] * weight_multiplier, 2)
            plans.append({
                "market": code,
                "shipping_zones": copy.deepcopy(ref["zones"]),
                "estimated_cost_per_unit": adjusted_cost,
                "estimated_transit_days": ref["transit_days"],
                "customs_notes": ref["customs"],
            })

        return {"status": "success", "shipping_plans": plans}
    except Exception as exc:
        return {"status": "error", "shipping_plans": [], "error": f"Shipping planning failed: {exc}"}
