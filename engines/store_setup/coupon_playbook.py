"""Niche-aware coupon playbook -- the 6 evergreen discount
types every Shopify store should have ready to mint.

``welcome_discount.py`` covers ONE code -- the launch
WELCOME{N} promo. Real merchants run 5-7 different
discount types over the year:

  * **Free shipping threshold** -- raise average order value
    by promising free shipping above a niche-appropriate
    cart total. Industry-standard AOV lift: 30%.
  * **Bundle** -- buy 2 get 10% off, buy 3 get 15%. Drives
    units-per-order.
  * **Loyalty / second-order** -- the second-purchase nudge,
    deepest LTV lever.
  * **Email subscriber** -- newsletter opt-in incentive.
  * **Cart recovery** -- abandoned-cart specific code.
  * **Seasonal / clearance** -- niche-appropriate
    end-of-season promo.

This module ships the structured discount params for each
of these so the operator (or autonomous controller) can
opt into any of them with a single call. None of them
are auto-applied -- the playbook generates the SPECS;
the operator decides which to mint.

Return shape from :func:`generate_playbook`::

    {
        "store_name": "Acme",
        "niche": "beauty",
        "discounts": [
            {
                "name": "free_shipping_threshold",
                "params": {...},  # ready for SHOPIFY_CREATE_DISCOUNT
                "rationale": "Beauty AOV is...",
                "when_to_enable": "Always-on",
            },
            ...
        ],
    }

The shape mirrors what ``welcome_discount.generate_welcome_discount``
returns, so the operator can pipe any one of these
directly into ``apply_welcome_discount`` (the function
is name-agnostic, applies any code).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Niche-specific thresholds + percentages. Each entry is
# tuned for the category's typical AOV + margin profile.
#
# free_shipping_threshold: cart total above which to drop
# shipping fees. Set to ~1.5x typical AOV so it's a real
# upsell, not a giveaway.
#
# bundle_pct: discount applied per bundle tier.
# loyalty_pct: second-order incentive.
# email_pct: newsletter opt-in.
# cart_recovery_pct: abandoned cart specific.
# seasonal_pct: clearance / end-of-season.
_NICHE_TUNING: dict[str, dict[str, Any]] = {
    "beauty": {
        "free_shipping_threshold": 50,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 15,
        "cart_recovery_pct": 10,
        "seasonal_pct": 20,
    },
    "fashion": {
        "free_shipping_threshold": 75,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 10,
        "cart_recovery_pct": 15,
        "seasonal_pct": 30,
    },
    "tech": {
        "free_shipping_threshold": 75,
        "bundle_pct_per_tier": (5, 10),
        "loyalty_pct": 5,
        "email_pct": 10,
        "cart_recovery_pct": 10,
        "seasonal_pct": 15,
    },
    "home": {
        "free_shipping_threshold": 100,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 10,
        "cart_recovery_pct": 10,
        "seasonal_pct": 20,
    },
    "food": {
        # Food often has free-shipping baked in;
        # threshold a touch lower.
        "free_shipping_threshold": 40,
        "bundle_pct_per_tier": (5, 10),
        "loyalty_pct": 10,
        "email_pct": 10,
        "cart_recovery_pct": 10,
        "seasonal_pct": 15,
    },
    "pets": {
        "free_shipping_threshold": 49,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 15,
        "cart_recovery_pct": 10,
        "seasonal_pct": 20,
    },
    "fitness": {
        "free_shipping_threshold": 75,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 15,
        "cart_recovery_pct": 15,
        "seasonal_pct": 25,
    },
    "jewelry": {
        # Tight margins on metal; smaller discounts.
        "free_shipping_threshold": 100,
        "bundle_pct_per_tier": (5, 10),
        "loyalty_pct": 5,
        "email_pct": 10,
        "cart_recovery_pct": 10,
        "seasonal_pct": 15,
    },
    "outdoor": {
        "free_shipping_threshold": 75,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 10,
        "cart_recovery_pct": 15,
        "seasonal_pct": 25,
    },
    "baby": {
        "free_shipping_threshold": 50,
        "bundle_pct_per_tier": (10, 15),
        "loyalty_pct": 10,
        "email_pct": 15,
        "cart_recovery_pct": 10,
        "seasonal_pct": 20,
    },
    "general": {
        "free_shipping_threshold": 50,
        "bundle_pct_per_tier": (5, 10),
        "loyalty_pct": 5,
        "email_pct": 10,
        "cart_recovery_pct": 10,
        "seasonal_pct": 15,
    },
}


def generate_playbook(
    *,
    store_name: str,
    niche: str = "general",
    days_valid: int = 365,
) -> dict[str, Any]:
    """Build the 6 evergreen discount specs for a niche.

    Args:
        store_name: Display name (interpolated into discount
            titles). Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            tuning.
        days_valid: How long each code stays valid from
            now (default 365 -- evergreens default to a
            year; seasonal can override per-code).

    Returns:
        ``{store_name, niche, discounts: [<6 entries>]}``.
        Each discount entry: ``{name, params, rationale,
        when_to_enable}``. The ``params`` dict is ready
        to feed into SHOPIFY_CREATE_DISCOUNT directly.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    tuning = _NICHE_TUNING.get(
        niche_n, _NICHE_TUNING["general"],
    )

    days = max(1, min(3650, int(days_valid or 365)))
    starts_at = datetime.now(timezone.utc)
    ends_at = starts_at + timedelta(days=days)

    discounts = [
        _free_shipping(name, tuning, starts_at, ends_at),
        _bundle(name, tuning, starts_at, ends_at),
        _loyalty(name, tuning, starts_at, ends_at),
        _email_subscriber(name, tuning, starts_at, ends_at),
        _cart_recovery(name, tuning, starts_at, ends_at),
        _seasonal(name, tuning, starts_at, ends_at),
    ]

    return {
        "store_name": name,
        "niche": niche_n,
        "discounts": discounts,
    }


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_shipping(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    threshold = int(tuning["free_shipping_threshold"])
    return {
        "name": "free_shipping_threshold",
        "params": {
            "code": f"FREESHIP{threshold}",
            "title": f"{name} free shipping over ${threshold}",
            # Free-shipping discount type -- not a percentage
            # off products. The friendly call shape uses a
            # ``free_shipping`` flag the adapter translates
            # to the appropriate Shopify FREE_SHIPPING
            # discount type.
            "free_shipping": True,
            "minimum_subtotal": float(threshold),
            "starts_at": _ts(starts),
            "ends_at": _ts(ends),
        },
        "rationale": (
            f"Free shipping above ${threshold} lifts AOV "
            f"~25-35% for this category."
        ),
        "when_to_enable": (
            "Always-on. Promote on every page header."
        ),
    }


def _bundle(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    pct_per_tier = tuning["bundle_pct_per_tier"]
    tier1_pct = int(pct_per_tier[0])
    return {
        "name": "bundle_10pct",
        "params": {
            "code": f"BUNDLE{tier1_pct}",
            "title": f"{name} bundle reward",
            "percentage": tier1_pct,
            # Bundle minimum purchase is the trigger.
            "minimum_item_count": 2,
            "starts_at": _ts(starts),
            "ends_at": _ts(ends),
        },
        "rationale": (
            f"Buy-2-get-{tier1_pct}% drives units-per-order. "
            "Same code stays live, customers self-qualify."
        ),
        "when_to_enable": (
            "Always-on. Promote on product pages + cart."
        ),
    }


def _loyalty(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    pct = int(tuning["loyalty_pct"])
    return {
        "name": "loyalty_second_order",
        "params": {
            "code": f"AGAIN{pct}",
            "title": f"{name} second-order reward",
            "percentage": pct,
            "usage_limit": None,
            "applies_once_per_customer": True,
            "starts_at": _ts(starts),
            "ends_at": _ts(ends),
        },
        "rationale": (
            "Repeat-purchase deepens LTV. The second order "
            "is the hardest to land."
        ),
        "when_to_enable": (
            "After first-order ships. Email + thank-you "
            "card insert."
        ),
    }


def _email_subscriber(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    pct = int(tuning["email_pct"])
    return {
        "name": "email_subscriber",
        "params": {
            "code": f"NEWSLETTER{pct}",
            "title": f"{name} newsletter signup reward",
            "percentage": pct,
            "applies_once_per_customer": True,
            "starts_at": _ts(starts),
            "ends_at": _ts(ends),
        },
        "rationale": (
            "Email captures are the highest-LTV channel. "
            f"A {pct}% nudge converts ~40-60% of visitors."
        ),
        "when_to_enable": (
            "Always-on. Exit-intent popup + footer signup."
        ),
    }


def _cart_recovery(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    pct = int(tuning["cart_recovery_pct"])
    return {
        "name": "cart_recovery",
        "params": {
            "code": f"COMEBACK{pct}",
            "title": f"{name} cart recovery",
            "percentage": pct,
            "usage_limit": None,
            "applies_once_per_customer": True,
            "starts_at": _ts(starts),
            "ends_at": _ts(ends),
        },
        "rationale": (
            f"Abandoned-cart emails recover 5-15% of "
            f"sessions; the {pct}% code lifts the recovery "
            "rate ~40% above no-code emails."
        ),
        "when_to_enable": (
            "Triggered: 1h post-abandonment in Klaviyo / "
            "Shopify Email."
        ),
    }


def _seasonal(
    name: str, tuning: dict[str, Any],
    starts: datetime, ends: datetime,
) -> dict[str, Any]:
    pct = int(tuning["seasonal_pct"])
    # Seasonal defaults to 90-day window even if the rest
    # of the playbook is yearly. Clearance is meant to be
    # time-bound + scarcity-driving.
    seasonal_ends = starts + timedelta(days=90)
    return {
        "name": "seasonal_clearance",
        "params": {
            "code": f"SEASON{pct}",
            "title": f"{name} seasonal clearance",
            "percentage": pct,
            "starts_at": _ts(starts),
            "ends_at": _ts(seasonal_ends),
        },
        "rationale": (
            f"End-of-season clearance at {pct}% moves "
            "stale inventory; scarcity (90-day window) "
            "drives urgency."
        ),
        "when_to_enable": (
            "Quarterly. Promote on the homepage banner "
            "+ via email."
        ),
    }
