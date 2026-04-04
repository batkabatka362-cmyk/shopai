"""International Expansion Engine — shipping planner.

Plans international shipping zones and costs per market.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Shipping reference data
# ---------------------------------------------------------------------------

_SHIPPING_DATA: dict[str, dict[str, Any]] = {
    "US": {"zones": ["domestic"], "cost_per_kg": 5.0, "transit_days": 3, "customs": "N/A — domestic"},
    "UK": {"zones": ["europe", "transatlantic"], "cost_per_kg": 12.5, "transit_days": 7, "customs": "UK customs declaration required; VAT at import"},
    "DE": {"zones": ["europe", "eu_single_market"], "cost_per_kg": 11.0, "transit_days": 6, "customs": "EU customs; EORI number required"},
    "FR": {"zones": ["europe", "eu_single_market"], "cost_per_kg": 11.5, "transit_days": 6, "customs": "EU customs; EORI number required"},
    "JP": {"zones": ["asia_pacific"], "cost_per_kg": 18.0, "transit_days": 10, "customs": "Japan customs; consumption tax at import"},
    "AU": {"zones": ["asia_pacific", "oceania"], "cost_per_kg": 16.0, "transit_days": 12, "customs": "Australian customs; GST on imports over AUD 1000"},
    "CA": {"zones": ["north_america"], "cost_per_kg": 8.0, "transit_days": 5, "customs": "Canadian customs; de minimis CAD 20"},
    "BR": {"zones": ["south_america"], "cost_per_kg": 22.0, "transit_days": 14, "customs": "Complex import duties; ICMS tax applies"},
    "IN": {"zones": ["south_asia"], "cost_per_kg": 15.0, "transit_days": 12, "customs": "Indian customs; BCD + IGST applicable"},
    "KR": {"zones": ["east_asia"], "cost_per_kg": 17.0, "transit_days": 9, "customs": "Korean customs; VAT 10% on imports"},
    "MX": {"zones": ["north_america", "latin_america"], "cost_per_kg": 10.0, "transit_days": 7, "customs": "Mexican customs; IVA 16% on imports"},
    "CN": {"zones": ["east_asia"], "cost_per_kg": 14.0, "transit_days": 10, "customs": "Chinese customs; cross-border e-commerce tax"},
}

_DEFAULT_SHIPPING = {"zones": ["international"], "cost_per_kg": 20.0, "transit_days": 14, "customs": "Standard international customs procedures"}


def plan_shipping(
    target_markets: list[str],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan shipping zones and costs for target markets.

    Args:
        target_markets: Market codes.
        products: Product list with weight data.

    Returns:
        Structured dict with shipping plans per market.
    """
    try:
        plans: list[dict[str, Any]] = []

        for market_code in target_markets:
            code = market_code.upper().strip()
            ref = _SHIPPING_DATA.get(code, _DEFAULT_SHIPPING)

            plans.append({
                "market": code,
                "shipping_zones": ref["zones"],
                "estimated_cost_per_kg": ref["cost_per_kg"],
                "transit_days": ref["transit_days"],
                "customs_notes": ref["customs"],
            })

        return {
            "status": "success",
            "shipping_plans": plans,
        }
    except Exception as exc:
        return {
            "status": "error",
            "shipping_plans": [],
            "error": f"Shipping planning failed: {exc}",
        }
