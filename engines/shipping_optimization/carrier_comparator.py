"""Shipping Optimization Engine — carrier comparator.

Compares USPS, UPS, FedEx, DHL across service levels, transit times,
reliability, and value.  Produces a ranked comparison table.

Model note: Would use Mistral for nuanced carrier capability analysis
and service-level matching based on product category and destination.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Carrier profiles (transit days by zone, reliability scores)
# ---------------------------------------------------------------------------

_CARRIER_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "USPS": {
        "ground_advantage": {
            "transit_days": {1: (2, 3), 2: (2, 4), 3: (3, 5), 4: (3, 6), 5: (4, 7), 6: (5, 8), 7: (6, 9), 8: (7, 10)},
            "reliability": 0.88,
            "tracking_quality": "basic",
            "insurance_included_usd": 0.0,
            "best_for": "lightweight_economy",
        },
        "priority_mail": {
            "transit_days": {1: (1, 2), 2: (1, 2), 3: (1, 3), 4: (2, 3), 5: (2, 3), 6: (2, 3), 7: (2, 3), 8: (2, 3)},
            "reliability": 0.93,
            "tracking_quality": "good",
            "insurance_included_usd": 100.0,
            "best_for": "mid_range_reliable",
        },
        "priority_mail_express": {
            "transit_days": {1: (1, 1), 2: (1, 1), 3: (1, 2), 4: (1, 2), 5: (1, 2), 6: (1, 2), 7: (1, 2), 8: (1, 2)},
            "reliability": 0.97,
            "tracking_quality": "excellent",
            "insurance_included_usd": 200.0,
            "best_for": "urgent_guaranteed",
        },
    },
    "UPS": {
        "ground": {
            "transit_days": {1: (1, 2), 2: (1, 3), 3: (2, 4), 4: (3, 5), 5: (3, 5), 6: (4, 6), 7: (5, 7), 8: (5, 7)},
            "reliability": 0.95,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "reliable_ground",
        },
        "3_day_select": {
            "transit_days": {1: (1, 2), 2: (1, 2), 3: (2, 3), 4: (2, 3), 5: (3, 3), 6: (3, 3), 7: (3, 3), 8: (3, 3)},
            "reliability": 0.96,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "mid_speed_business",
        },
        "2nd_day_air": {
            "transit_days": {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2), 5: (2, 2), 6: (2, 2), 7: (2, 2), 8: (2, 2)},
            "reliability": 0.97,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "fast_reliable",
        },
        "next_day_air": {
            "transit_days": {1: (1, 1), 2: (1, 1), 3: (1, 1), 4: (1, 1), 5: (1, 1), 6: (1, 1), 7: (1, 1), 8: (1, 1)},
            "reliability": 0.99,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "overnight_premium",
        },
    },
    "FedEx": {
        "ground": {
            "transit_days": {1: (1, 2), 2: (1, 3), 3: (2, 4), 4: (2, 5), 5: (3, 5), 6: (4, 6), 7: (4, 7), 8: (5, 7)},
            "reliability": 0.94,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "reliable_ground",
        },
        "express_saver": {
            "transit_days": {1: (1, 2), 2: (2, 3), 3: (2, 3), 4: (3, 3), 5: (3, 3), 6: (3, 3), 7: (3, 3), 8: (3, 3)},
            "reliability": 0.96,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "mid_speed_value",
        },
        "2day": {
            "transit_days": {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2), 5: (2, 2), 6: (2, 2), 7: (2, 2), 8: (2, 2)},
            "reliability": 0.97,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "fast_ecommerce",
        },
        "overnight": {
            "transit_days": {1: (1, 1), 2: (1, 1), 3: (1, 1), 4: (1, 1), 5: (1, 1), 6: (1, 1), 7: (1, 1), 8: (1, 1)},
            "reliability": 0.99,
            "tracking_quality": "excellent",
            "insurance_included_usd": 100.0,
            "best_for": "overnight_premium",
        },
    },
    "DHL": {
        "ecommerce": {
            "transit_days": {1: (3, 5), 2: (3, 6), 3: (4, 7), 4: (5, 8), 5: (5, 9), 6: (6, 10), 7: (7, 11), 8: (7, 12)},
            "reliability": 0.85,
            "tracking_quality": "basic",
            "insurance_included_usd": 0.0,
            "best_for": "budget_bulk",
        },
        "parcel": {
            "transit_days": {1: (2, 3), 2: (2, 4), 3: (3, 5), 4: (3, 5), 5: (4, 6), 6: (4, 7), 7: (5, 7), 8: (5, 8)},
            "reliability": 0.90,
            "tracking_quality": "good",
            "insurance_included_usd": 0.0,
            "best_for": "international_domestic_mix",
        },
        "express": {
            "transit_days": {1: (1, 1), 2: (1, 1), 3: (1, 2), 4: (1, 2), 5: (1, 2), 6: (1, 2), 7: (1, 2), 8: (2, 2)},
            "reliability": 0.96,
            "tracking_quality": "excellent",
            "insurance_included_usd": 0.0,
            "best_for": "express_international",
        },
    },
}


def compare_carriers(
    rates: list[dict[str, Any]],
    zone: int = 5,
    priority: str = "value",
) -> dict[str, Any]:
    """Compare carriers using computed rates and carrier profiles.

    Args:
        rates: List of ShippingRate dicts from rate_calculator.
        zone: Shipping zone for transit-time lookup.
        priority: One of 'cost', 'speed', 'value', 'reliability'.

    Returns:
        Structured dict with ranked CarrierComparison list.
    """
    try:
        zone = max(1, min(8, int(zone)))
        comparisons: list[dict[str, Any]] = []

        for rate_entry in copy.deepcopy(rates):
            carrier = rate_entry.get("carrier", "")
            service = rate_entry.get("service", "")
            total = float(rate_entry.get("total", 0.0))

            profile = _CARRIER_PROFILES.get(carrier, {}).get(service, {})
            if not profile:
                continue

            transit = profile.get("transit_days", {}).get(zone, (5, 10))
            reliability = float(profile.get("reliability", 0.85))
            best_for = profile.get("best_for", "general")

            # Value score: lower is better.
            # Weighted blend of cost, speed, and reliability.
            avg_transit = (transit[0] + transit[1]) / 2.0
            cost_norm = total / 50.0  # normalise to ~0-1 range
            speed_norm = avg_transit / 10.0
            reliability_norm = 1.0 - reliability

            if priority == "cost":
                value_score = cost_norm * 0.70 + speed_norm * 0.15 + reliability_norm * 0.15
            elif priority == "speed":
                value_score = cost_norm * 0.15 + speed_norm * 0.70 + reliability_norm * 0.15
            elif priority == "reliability":
                value_score = cost_norm * 0.15 + speed_norm * 0.15 + reliability_norm * 0.70
            else:  # value (balanced)
                value_score = cost_norm * 0.40 + speed_norm * 0.35 + reliability_norm * 0.25

            comparisons.append({
                "carrier": carrier,
                "service": service,
                "rate": total,
                "transit_days_min": transit[0],
                "transit_days_max": transit[1],
                "reliability_score": reliability,
                "value_score": round(value_score, 4),
                "best_for": best_for,
            })

        comparisons.sort(key=lambda c: c["value_score"])

        # Mark the top pick
        best = comparisons[0] if comparisons else None

        return {
            "status": "success",
            "comparisons": comparisons,
            "count": len(comparisons),
            "best": best,
            "priority_used": priority,
            "model_note": "Mistral: carrier capability analysis and service-level matching",
        }
    except Exception as exc:
        return {
            "status": "error",
            "comparisons": [],
            "count": 0,
            "best": None,
            "priority_used": priority,
            "error": f"Carrier comparison failed: {exc}",
        }
