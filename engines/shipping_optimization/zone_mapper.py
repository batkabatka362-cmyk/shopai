"""Shipping Optimization Engine — zone mapper.

Maps origin ZIP to shipping zones (1-8) and computes the expected
zone distribution for a US-based e-commerce merchant.

Zone mapping uses the first 3 digits of the ZIP code (ZIP3 prefix)
with a realistic distance-based model.  Zone distribution reflects
US population density by region.

No LLM calls — deterministic geography.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# ZIP3 prefix → US region mapping
# ---------------------------------------------------------------------------
# Regions: NE (Northeast), SE (Southeast), MW (Midwest),
#          SW (Southwest), W (West), NW (Northwest)

def _zip3_to_region(zip3: int) -> str:
    """Map a 3-digit ZIP prefix to a US region."""
    if 0 <= zip3 <= 99:
        return "NE"     # CT, MA, ME, NH, NJ, NY, PR, RI, VT, VI
    elif 100 <= zip3 <= 199:
        return "NE"     # NY
    elif 200 <= zip3 <= 299:
        return "NE"     # DC, MD, PA, VA, WV
    elif 300 <= zip3 <= 399:
        return "SE"     # AL, FL, GA, MS, TN
    elif 400 <= zip3 <= 499:
        return "MW"     # IN, KY, MI, OH
    elif 500 <= zip3 <= 599:
        return "MW"     # IA, MN, MT, ND, NE, SD, WI
    elif 600 <= zip3 <= 699:
        return "MW"     # IL, KS, MO
    elif 700 <= zip3 <= 799:
        return "SW"     # AR, LA, OK, TX
    elif 800 <= zip3 <= 899:
        return "SW"     # AZ, CO, ID, NM, NV, UT, WY
    elif 900 <= zip3 <= 961:
        return "W"      # CA
    elif 962 <= zip3 <= 979:
        return "NW"     # OR, WA
    elif 980 <= zip3 <= 999:
        return "NW"     # WA, AK, HI
    return "MW"  # fallback


# Region-to-region zone matrix
_ZONE_MATRIX: dict[str, dict[str, int]] = {
    "NE": {"NE": 2, "SE": 4, "MW": 4, "SW": 6, "W": 7, "NW": 8},
    "SE": {"NE": 4, "SE": 2, "MW": 4, "SW": 4, "W": 6, "NW": 7},
    "MW": {"NE": 4, "SE": 4, "MW": 2, "SW": 4, "W": 5, "NW": 5},
    "SW": {"NE": 6, "SE": 4, "MW": 4, "SW": 2, "W": 4, "NW": 5},
    "W":  {"NE": 7, "SE": 6, "MW": 5, "SW": 4, "W": 2, "NW": 3},
    "NW": {"NE": 8, "SE": 7, "MW": 5, "SW": 5, "W": 3, "NW": 2},
}

# US population distribution by region (approximate, for zone distribution)
_POPULATION_DIST: dict[str, float] = {
    "NE": 0.22,
    "SE": 0.24,
    "MW": 0.21,
    "SW": 0.15,
    "W":  0.12,
    "NW": 0.06,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_zones(
    origin_zip: str = "10001",
) -> dict[str, Any]:
    """Map origin ZIP to zones and compute zone distribution.

    Uses population-weighted zone distribution to estimate the percentage
    of orders that will fall into each zone.

    Args:
        origin_zip: Merchant's warehouse/fulfillment ZIP code.

    Returns:
        Structured dict with zone distribution and weighted average zone.
    """
    try:
        zip_str = str(origin_zip).strip().zfill(5)
        zip3 = int(zip_str[:3])
        origin_region = _zip3_to_region(zip3)

        # Build zone distribution
        zone_dist: dict[int, float] = {}  # zone -> pct_of_orders
        zone_regions: dict[int, list[str]] = {}  # zone -> list of regions

        for dest_region, pop_pct in _POPULATION_DIST.items():
            zone = _ZONE_MATRIX.get(origin_region, {}).get(dest_region, 5)
            # Local zone 1 gets a small bump (same-city deliveries)
            if origin_region == dest_region:
                # Split: 15% of local region is zone 1, rest is mapped zone
                z1_pct = pop_pct * 0.15
                rest_pct = pop_pct * 0.85
                zone_dist[1] = zone_dist.get(1, 0.0) + z1_pct
                zone_dist[zone] = zone_dist.get(zone, 0.0) + rest_pct
                zone_regions.setdefault(1, []).append(f"{dest_region}(local)")
                zone_regions.setdefault(zone, []).append(dest_region)
            else:
                zone_dist[zone] = zone_dist.get(zone, 0.0) + pop_pct
                zone_regions.setdefault(zone, []).append(dest_region)

        # Normalize to ensure sum = 1.0
        total = sum(zone_dist.values())
        if total > 0:
            zone_dist = {z: pct / total for z, pct in zone_dist.items()}

        # Build output list
        distribution: list[dict[str, Any]] = []
        for zone in sorted(zone_dist.keys()):
            pct = zone_dist[zone]
            distribution.append({
                "zone": zone,
                "pct_of_orders": round(pct, 4),
                "regions": zone_regions.get(zone, []),
            })

        # Weighted average zone
        weighted_zone = sum(z * pct for z, pct in zone_dist.items())

        return {
            "status": "success",
            "distribution": distribution,
            "origin": {
                "zip": zip_str,
                "zip3": zip3,
                "region": origin_region,
            },
            "weighted_avg_zone": round(weighted_zone, 2),
            "zone_count": len(distribution),
        }
    except Exception as exc:
        return {
            "status": "error",
            "distribution": [],
            "origin": {"zip": str(origin_zip), "zip3": 0, "region": "unknown"},
            "weighted_avg_zone": 5.0,
            "zone_count": 0,
            "error": f"Zone mapping failed: {exc}",
        }
