"""Niche-aware inventory reorder threshold recommender.

The ``inventory`` engine ships with sensible defaults
(``lead_time_days=7``, ``service_level_target=0.95``,
sensible reorder formulas). But the OPTIMAL values are
heavily niche-dependent:

  * Beauty: 7-14 day lead times (US distributors), 95%
    service level (out-of-stock = lost first-order).
  * Fashion: 21-45 day lead times (seasonal imports),
    90% service level (slow movers cost shelf space).
  * Tech: 14-30 day lead times, 95% (warranty
    commitments depend on stock).
  * Food: 3-7 day lead times (perishable), 98% service
    level (subscription customers churn on stockouts).
  * Pets: 7-14 day lead times, 97% (subscription food).
  * Jewelry: 30-60 day lead times (custom + made-to-
    order), 90% service level (low velocity).

This module ships per-niche defaults the inventory
engine consumes when the operator doesn't override.

The shape is drop-in compatible with what
``inventory.safety_stock_optimizer.optimize_safety_stock``
expects via per-product ``lead_time_days`` +
``service_level_target`` kwarg.

Return shape from :func:`generate_inventory_thresholds`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "defaults": {
            "lead_time_days": 10,
            "service_level_target": 0.95,
            "reorder_buffer_pct": 0.20,
            "min_stock_threshold_units": 5,
            "max_stock_threshold_units": 200,
            "stockout_cost_per_day_usd": 25.0,
        },
        "rationale": "...",
    }

These are RECOMMENDATIONS the operator pastes into the
inventory engine's config or per-product metafields.
The actual numbers come from real ecommerce ops -- they
encode "what the category typically needs" so a fresh
merchant doesn't start from blank defaults.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Per-niche tuning. Each tuple: (lead_time_days,
# service_level_target, reorder_buffer_pct,
# min_stock_threshold_units, max_stock_threshold_units,
# stockout_cost_per_day_usd, rationale).
_NICHE_TUNING: dict[
    str,
    tuple[int, float, float, int, int, float, str],
] = {
    "beauty": (
        10,    # lead_time_days
        0.95,  # service_level_target
        0.20,  # reorder_buffer_pct
        5,     # min_stock_threshold
        200,   # max_stock_threshold
        25.0,  # stockout_cost_per_day_usd
        "Beauty: US distributor lead times 7-14 days; "
        "stockouts on routine items lose first-order "
        "conversions worth ~$25/day per SKU.",
    ),
    "fashion": (
        30,    # lead_time_days (seasonal imports)
        0.90,  # service_level_target
        0.15,  # reorder_buffer_pct (lower -- shelf space
               # is the constraint)
        3,
        150,
        15.0,
        "Fashion: seasonal imports drive 3-6 week lead "
        "times. Lower service level + lower buffer "
        "because shelf-space carry cost > stockout cost "
        "for slow-moving lines.",
    ),
    "tech": (
        21,
        0.95,
        0.20,
        5,
        100,
        40.0,
        "Tech: 14-30 day lead times from manufacturers; "
        "stockouts on warranty-eligible products cost "
        "~$40/day (replacement + support overhead).",
    ),
    "home": (
        21,
        0.92,
        0.18,
        2,
        80,
        20.0,
        "Home goods: 2-3 week lead times for ceramics + "
        "wood; lower turnover = lower service level + "
        "smaller stock bands.",
    ),
    "food": (
        5,     # perishable -- short lead times
        0.98,  # subscription customers churn fast on
               # stockouts
        0.25,  # higher buffer for perishable spoilage
        10,
        300,
        50.0,
        "Food: short lead times (3-7 days), highest "
        "service level (98%); subscription churn on a "
        "stockout costs ~$50/day per SKU.",
    ),
    "pets": (
        10,
        0.97,
        0.22,
        10,
        250,
        35.0,
        "Pets: monthly subscription cadence for food + "
        "treats means high service level; stockouts on "
        "primary protein source cost subscriber churn.",
    ),
    "fitness": (
        21,
        0.93,
        0.18,
        5,
        120,
        25.0,
        "Fitness: 2-3 week lead times for apparel + "
        "supplements; medium service level (athletes "
        "tolerate some delay if alternatives exist in "
        "the catalog).",
    ),
    "jewelry": (
        45,    # made-to-order / custom
        0.90,
        0.10,  # very low buffer -- jewelry sits on the
               # shelf forever
        1,
        30,
        100.0,
        "Jewelry: 30-60 day lead times for custom + "
        "made-to-order; very low buffer because "
        "carrying cost is high (precious metals + "
        "stones).",
    ),
    "outdoor": (
        28,
        0.92,
        0.18,
        3,
        100,
        30.0,
        "Outdoor: ~4 week lead times for technical gear; "
        "seasonal demand (camping in summer / skiing in "
        "winter) means medium service level.",
    ),
    "baby": (
        10,
        0.97,
        0.22,
        10,
        300,
        45.0,
        "Baby: high service level (97%); diapers + "
        "formula + clothing have subscription-like "
        "cadence with strict reliability needs.",
    ),
    "general": (
        14,
        0.95,
        0.20,
        5,
        150,
        25.0,
        "General fallback: 2-week lead time, 95% "
        "service level, 20% buffer -- conservative "
        "defaults safe for any category.",
    ),
}


def generate_inventory_thresholds(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware inventory threshold defaults.

    Args:
        store_name: Display name (returned for context).
            Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, defaults: {...}, rationale}``.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    tuning = _NICHE_TUNING.get(
        niche_n, _NICHE_TUNING["general"],
    )
    (
        lead_time, service, buffer_pct, min_th,
        max_th, stockout_cost, rationale,
    ) = tuning

    return {
        "store_name": name,
        "niche": niche_n,
        "defaults": {
            "lead_time_days": int(lead_time),
            "service_level_target": float(service),
            "reorder_buffer_pct": float(buffer_pct),
            "min_stock_threshold_units": int(min_th),
            "max_stock_threshold_units": int(max_th),
            "stockout_cost_per_day_usd": float(
                stockout_cost,
            ),
        },
        "rationale": rationale,
    }


def hand_off_to_inventory_engine(
    template: dict[str, Any],
) -> dict[str, Any]:
    """Translate the recommendation into the kwargs the
    inventory engine consumes.

    ``inventory.flow.InventoryEngine`` accepts a config
    dict; this function returns the slice that maps to
    threshold + service-level inputs.
    """
    if (
        not isinstance(template, dict)
        or not template.get("defaults")
    ):
        return {}
    defaults = template["defaults"]
    return {
        # safety_stock_optimizer kwarg
        "service_level_target": defaults[
            "service_level_target"
        ],
        # alert_generator + reorder_calculator inputs
        "lead_time_days": defaults["lead_time_days"],
        "reorder_buffer_pct": defaults[
            "reorder_buffer_pct"
        ],
        "min_stock_threshold_units": defaults[
            "min_stock_threshold_units"
        ],
        "max_stock_threshold_units": defaults[
            "max_stock_threshold_units"
        ],
        # cost_tracker + alert_generator urgency input
        "stockout_cost_per_day_usd": defaults[
            "stockout_cost_per_day_usd"
        ],
    }
