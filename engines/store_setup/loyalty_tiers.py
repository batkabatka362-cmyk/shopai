"""Niche-aware loyalty tier templates.

The `engines.loyalty.program_designer` module ships a single
default tier set (bronze/silver/gold/platinum at fixed
thresholds 0/1000/5000/15000) plus a default
``points_per_dollar=10``. That's a good starting point, but
the right thresholds + earn rate are heavily niche-dependent:

  * Beauty AOV is $40-60; 10pts/$1 + 1000-point silver
    means ~$100 spend = silver. Reasonable.
  * Jewelry AOV is $200-500; the same rates mean
    $100 = silver -- too quick. Real jewelry programs
    use $1=1pt and silver at $2k spend.
  * Food (subscription-heavy) wants lower thresholds so
    customers feel rewarded faster.

This module ships per-niche tier templates + earn rates
tuned to category AOV / typical purchase cadence, ready to
feed into ``loyalty.program_designer.design_program`` as
the ``program_config["tiers"]`` + ``points_per_dollar``
inputs.

Return shape from :func:`generate_tier_template`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "points_per_dollar": 10.0,
        "tiers": [
            {
                "name": "bronze",
                "min_points": 0,
                "multiplier": 1.0,
                "benefits": [...],
            },
            ...
        ],
    }

Drop-in compatible with the existing
``program_designer.design_program`` -- callers pass the
returned dict as ``program_config``.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Niche-specific tuning. Each entry: (points_per_dollar,
# bronze min, silver min, gold min, platinum min).
#
# Tuning philosophy:
#   * silver target = ~2x typical AOV (achievable in 2-3
#     orders for repeat buyers)
#   * gold target = ~10x AOV (committed customer)
#   * platinum target = ~30x AOV (whales)
#   * points_per_dollar tuned so the AOV-spend math is
#     intuitive: $1 spend yields 1-10 points depending on
#     category margin profile.
_NICHE_TIER_TUNING: dict[
    str, tuple[float, int, int, int, int],
] = {
    # Beauty: AOV ~$50, 10pts/$1 -> silver=$100, gold=$500,
    # platinum=$1500. Good cadence for skincare buyers.
    "beauty": (10.0, 0, 1000, 5000, 15000),
    # Fashion: AOV ~$80, 10pts/$1 -> silver=$200, gold=$800,
    # platinum=$2500. Aligned with typical wardrobe-spend.
    "fashion": (10.0, 0, 2000, 8000, 25000),
    # Tech: AOV ~$150, 5pts/$1 -> silver=$400, gold=$1600,
    # platinum=$5000. Higher prices, slower point accrual.
    "tech": (5.0, 0, 2000, 8000, 25000),
    # Home: AOV ~$120, 5pts/$1 -> silver=$300, gold=$1500,
    # platinum=$5000.
    "home": (5.0, 0, 1500, 7500, 25000),
    # Food: low AOV ~$40 but high frequency, 10pts/$1 ->
    # silver=$80, gold=$400, platinum=$1500. Fast feedback
    # for subscription customers.
    "food": (10.0, 0, 800, 4000, 15000),
    # Pets: similar to food, AOV ~$50 with monthly cadence.
    "pets": (10.0, 0, 1000, 5000, 15000),
    # Fitness: mixed AOV (apparel $80 + supplements $30),
    # 10pts/$1 -> silver=$150, gold=$600, platinum=$2000.
    "fitness": (10.0, 0, 1500, 6000, 20000),
    # Jewelry: high AOV $300-800, 1pt/$1 -> silver=$2k,
    # gold=$10k, platinum=$30k. Industry-standard rates.
    "jewelry": (1.0, 0, 2000, 10000, 30000),
    # Outdoor: AOV ~$120, 5pts/$1 -> silver=$300, gold=$1500,
    # platinum=$5000.
    "outdoor": (5.0, 0, 1500, 7500, 25000),
    # Baby: AOV ~$60 with high purchase frequency in first
    # year. 10pts/$1 -> silver=$120, gold=$600, platinum=$2k.
    # Fast accrual for new-parent loyalty.
    "baby": (10.0, 0, 1200, 6000, 20000),
    # General fallback
    "general": (10.0, 0, 1000, 5000, 15000),
}


# Niche-specific benefits. Each tier inherits the lower
# tier's benefits + adds its own.
_NICHE_BENEFITS: dict[str, dict[str, list[str]]] = {
    "beauty": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_samples_with_order", "early_access"],
        "gold": ["free_shipping", "exclusive_shades"],
        "platinum": ["personal_consultations",
                     "vip_launches"],
    },
    "fashion": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_shipping_over_50", "early_access"],
        "gold": ["free_shipping", "exclusive_collections"],
        "platinum": ["personal_stylist", "private_sales"],
    },
    "tech": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["extended_warranty", "early_access"],
        "gold": ["free_shipping", "priority_support"],
        "platinum": ["dedicated_account_manager",
                     "beta_access"],
    },
    "home": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_shipping_over_75",
                   "early_access"],
        "gold": ["free_shipping", "design_consultations"],
        "platinum": ["personal_designer",
                     "trade_pricing"],
    },
    "food": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["subscription_discount", "early_access"],
        "gold": ["free_shipping", "limited_releases"],
        "platinum": ["chef_curated_picks",
                     "tasting_events"],
    },
    "pets": {
        "bronze": ["basic_rewards", "pet_birthday_bonus"],
        "silver": ["subscription_discount", "early_access"],
        "gold": ["free_shipping", "vet_consultations"],
        "platinum": ["custom_meal_plans",
                     "annual_health_pack"],
    },
    "fitness": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_shipping_over_75",
                   "early_access"],
        "gold": ["free_shipping", "coaching_credits"],
        "platinum": ["1on1_coaching",
                     "annual_supplement_audit"],
    },
    "jewelry": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_resize", "engraving_credit"],
        "gold": ["free_shipping", "annual_polish"],
        "platinum": ["custom_design_consultation",
                     "appraisal_service"],
    },
    "outdoor": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_shipping_over_75",
                   "gear_repair_credit"],
        "gold": ["free_shipping", "lifetime_warranty_ext"],
        "platinum": ["pro_gear_access",
                     "expedition_consultations"],
    },
    "baby": {
        "bronze": ["basic_rewards", "baby_birthday_bonus"],
        "silver": ["subscription_discount",
                   "stage_recommendations"],
        "gold": ["free_shipping", "early_access_drops"],
        "platinum": ["parent_consultations",
                     "milestone_bundles"],
    },
    "general": {
        "bronze": ["basic_rewards", "birthday_bonus"],
        "silver": ["free_shipping_over_50", "early_access"],
        "gold": ["free_shipping", "exclusive_deals"],
        "platinum": ["vip_events", "concierge_support"],
    },
}


# Multipliers stay consistent across niches -- the math
# below depends on them.
_TIER_NAMES: tuple[str, ...] = (
    "bronze", "silver", "gold", "platinum",
)
_TIER_MULTIPLIERS: dict[str, float] = {
    "bronze": 1.0,
    "silver": 1.25,
    "gold": 1.5,
    "platinum": 2.0,
}


def generate_tier_template(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build a niche-tuned loyalty program config.

    Args:
        store_name: Display name (returned for context).
            Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.

    Returns:
        ``{store_name, niche, points_per_dollar, tiers}``.
        The shape is drop-in compatible with
        ``loyalty.program_designer.design_program``'s
        ``program_config`` arg.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    tuning = _NICHE_TIER_TUNING.get(
        niche_n, _NICHE_TIER_TUNING["general"],
    )
    benefits_table = _NICHE_BENEFITS.get(
        niche_n, _NICHE_BENEFITS["general"],
    )

    points_per_dollar, bronze_min, silver_min, gold_min, plat_min = (
        tuning
    )
    thresholds = {
        "bronze": bronze_min,
        "silver": silver_min,
        "gold": gold_min,
        "platinum": plat_min,
    }

    # Each tier inherits the lower tier's benefits +
    # adds its own.
    accumulated_benefits: list[str] = []
    tiers: list[dict[str, Any]] = []
    for tier_name in _TIER_NAMES:
        tier_benefits = benefits_table.get(tier_name, [])
        accumulated_benefits = (
            accumulated_benefits + tier_benefits
        )
        # Dedupe -- preserve first-occurrence order.
        seen: set[str] = set()
        deduped: list[str] = []
        for b in accumulated_benefits:
            if b not in seen:
                deduped.append(b)
                seen.add(b)
        accumulated_benefits = deduped
        tiers.append({
            "name": tier_name,
            "min_points": int(thresholds[tier_name]),
            "multiplier": float(
                _TIER_MULTIPLIERS[tier_name]
            ),
            "benefits": list(accumulated_benefits),
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "points_per_dollar": float(points_per_dollar),
        "tiers": tiers,
    }


def hand_off_to_program_designer(
    template: dict[str, Any],
    *,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate the rich template into the
    ``program_config`` shape that
    ``loyalty.program_designer.design_program`` consumes.

    ``design_program`` accepts ``tier_thresholds`` (a flat
    ``{name: min_points}`` dict) plus ``points_per_dollar``,
    and merges those with hardcoded multipliers + benefits.
    The niche-aware MULTIPLIERS + BENEFITS in the template
    therefore aren't consumed by ``design_program`` today;
    they're available for callers that go directly to
    ``tier_manager.manage_tiers``, which DOES accept the
    full tier list.

    Args:
        template: Output of :func:`generate_tier_template`.
        extra_config: Optional extra fields to merge into
            the program_config (e.g. expiration_months,
            program_name).

    Returns:
        Ready-to-pass ``program_config`` dict. Empty when
        the template is empty / non-dict.
    """
    if (
        not isinstance(template, dict)
        or not template.get("tiers")
    ):
        return {}

    config: dict[str, Any] = {
        "tier_thresholds": {
            t["name"]: t["min_points"]
            for t in template["tiers"]
        },
        "points_per_dollar": (
            template["points_per_dollar"]
        ),
    }
    if isinstance(extra_config, dict):
        for k, v in extra_config.items():
            # Don't let extras stomp the niche-tuned
            # threshold / rate fields silently.
            if k in (
                "tier_thresholds", "points_per_dollar",
            ):
                continue
            config[k] = v
    return config


def hand_off_to_tier_manager(
    template: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the tier list ready for
    ``loyalty.tier_manager.manage_tiers``.

    Unlike :func:`hand_off_to_program_designer`, this
    preserves the niche-aware multipliers + benefits.
    """
    if (
        not isinstance(template, dict)
        or not template.get("tiers")
    ):
        return []
    return list(template["tiers"])
