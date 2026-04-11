"""Shipping Optimization Engine — rate calculator.

Calculates shipping rates based on weight, dimensions, and shipping zone
using realistic carrier rate tables.  Applies dimensional-weight pricing,
residential surcharges, and fuel surcharges.

No LLM calls — pure arithmetic from rate tables.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Carrier rate tables (per-zone, weight-bracket based)
# Rates are in USD.  Dimensional divisor in cm -> kg.
# ---------------------------------------------------------------------------

_DIM_DIVISOR_CM = 5000.0  # standard volumetric divisor (cm)

# Zone multipliers  (zone 1 = local, zone 8 = cross-country)
_ZONE_MULTIPLIERS = {
    1: 1.00, 2: 1.08, 3: 1.18, 4: 1.30,
    5: 1.45, 6: 1.62, 7: 1.80, 8: 2.00,
}

# Base rates per carrier + service.  Structure:
#   { carrier: { service: { "base": float, "per_kg": float,
#                            "fuel_surcharge_pct": float,
#                            "residential_surcharge": float } } }
_RATE_TABLES: dict[str, dict[str, dict[str, float]]] = {
    "USPS": {
        "ground_advantage": {
            "base": 4.50, "per_kg": 0.85,
            "fuel_surcharge_pct": 0.0, "residential_surcharge": 0.0,
        },
        "priority_mail": {
            "base": 7.90, "per_kg": 1.25,
            "fuel_surcharge_pct": 0.0, "residential_surcharge": 0.0,
        },
        "priority_mail_express": {
            "base": 26.35, "per_kg": 2.10,
            "fuel_surcharge_pct": 0.0, "residential_surcharge": 0.0,
        },
    },
    "UPS": {
        "ground": {
            "base": 9.45, "per_kg": 1.10,
            "fuel_surcharge_pct": 0.08, "residential_surcharge": 5.15,
        },
        "3_day_select": {
            "base": 14.20, "per_kg": 1.55,
            "fuel_surcharge_pct": 0.08, "residential_surcharge": 5.15,
        },
        "2nd_day_air": {
            "base": 21.50, "per_kg": 2.35,
            "fuel_surcharge_pct": 0.08, "residential_surcharge": 5.15,
        },
        "next_day_air": {
            "base": 38.75, "per_kg": 3.80,
            "fuel_surcharge_pct": 0.10, "residential_surcharge": 5.15,
        },
    },
    "FedEx": {
        "ground": {
            "base": 9.80, "per_kg": 1.15,
            "fuel_surcharge_pct": 0.075, "residential_surcharge": 5.30,
        },
        "express_saver": {
            "base": 15.10, "per_kg": 1.65,
            "fuel_surcharge_pct": 0.075, "residential_surcharge": 5.30,
        },
        "2day": {
            "base": 22.00, "per_kg": 2.40,
            "fuel_surcharge_pct": 0.075, "residential_surcharge": 5.30,
        },
        "overnight": {
            "base": 40.25, "per_kg": 4.00,
            "fuel_surcharge_pct": 0.11, "residential_surcharge": 5.30,
        },
    },
    "DHL": {
        "ecommerce": {
            "base": 4.80, "per_kg": 0.90,
            "fuel_surcharge_pct": 0.05, "residential_surcharge": 0.0,
        },
        "parcel": {
            "base": 8.50, "per_kg": 1.20,
            "fuel_surcharge_pct": 0.05, "residential_surcharge": 0.0,
        },
        "express": {
            "base": 32.00, "per_kg": 3.50,
            "fuel_surcharge_pct": 0.12, "residential_surcharge": 0.0,
        },
    },
}

# Weight brackets for additional handling surcharges
_OVERSIZE_THRESHOLD_KG = 31.5  # ~70 lbs
_OVERSIZE_SURCHARGE = 12.50
_LONGEST_SIDE_THRESHOLD_CM = 122.0  # 48 in
_LONGEST_SIDE_SURCHARGE = 18.00


def calculate_rates(
    products: list[dict[str, Any]],
    zone: int = 5,
) -> dict[str, Any]:
    """Calculate shipping rates for a list of products across all carriers.

    Assumes all products ship in one combined shipment.

    Args:
        products: List of ProductItem dicts.
        zone: Shipping zone (1-8).

    Returns:
        Structured dict with list of ShippingRate dicts.
    """
    try:
        items = copy.deepcopy(products)
        zone = max(1, min(8, int(zone)))

        total_weight_kg = _total_weight(items)
        total_dim_weight_kg = _total_dimensional_weight(items)
        billable_weight_kg = max(total_weight_kg, total_dim_weight_kg)
        longest_side_cm = _longest_side(items)

        zone_mult = _ZONE_MULTIPLIERS.get(zone, 1.0)

        rates: list[dict[str, Any]] = []

        for carrier, services in _RATE_TABLES.items():
            for service, table in services.items():
                base = table["base"]
                per_kg = table["per_kg"]
                fuel_pct = table["fuel_surcharge_pct"]
                residential = table["residential_surcharge"]

                # Core rate
                core = (base + billable_weight_kg * per_kg) * zone_mult

                # Fuel surcharge
                fuel = core * fuel_pct

                # Surcharges
                surcharges = residential
                if billable_weight_kg > _OVERSIZE_THRESHOLD_KG:
                    surcharges += _OVERSIZE_SURCHARGE
                if longest_side_cm > _LONGEST_SIDE_THRESHOLD_CM:
                    surcharges += _LONGEST_SIDE_SURCHARGE

                total = core + fuel + surcharges

                rates.append({
                    "carrier": carrier,
                    "service": service,
                    "rate": round(core, 2),
                    "zone": zone,
                    "weight_kg": round(total_weight_kg, 3),
                    "dimensional_weight_kg": round(total_dim_weight_kg, 3),
                    "billable_weight_kg": round(billable_weight_kg, 3),
                    "surcharges": round(fuel + surcharges, 2),
                    "total": round(total, 2),
                })

        rates.sort(key=lambda r: r["total"])

        return {
            "status": "success",
            "rates": rates,
            "count": len(rates),
            "cheapest": rates[0] if rates else None,
            "zone": zone,
        }
    except Exception as exc:
        return {
            "status": "error",
            "rates": [],
            "count": 0,
            "cheapest": None,
            "zone": zone,
            "error": f"Rate calculation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _total_weight(products: list[dict[str, Any]]) -> float:
    """Sum actual weight of all products."""
    return sum(float(p.get("weight_kg", 0.5)) for p in products)


def _total_dimensional_weight(products: list[dict[str, Any]]) -> float:
    """Sum dimensional weight of all products."""
    total = 0.0
    for p in products:
        dims = p.get("dimensions", {})
        l = float(dims.get("l", 20.0))
        w = float(dims.get("w", 15.0))
        h = float(dims.get("h", 10.0))
        total += (l * w * h) / _DIM_DIVISOR_CM
    return total


def _longest_side(products: list[dict[str, Any]]) -> float:
    """Find the longest single dimension across all products."""
    longest = 0.0
    for p in products:
        dims = p.get("dimensions", {})
        for key in ("l", "w", "h"):
            val = float(dims.get(key, 0.0))
            if val > longest:
                longest = val
    return longest
