"""Niche-aware customer segment starter pack.

Customer segments are Shopify's native filter primitive for
the customer list. The autonomous-launch story is incomplete
without them -- engines that target customer cohorts
(``loyalty``, ``churn_prediction``, ``email_marketing``,
``dynamic_pricing``'s tier logic) all assume the segments
already exist.

This module ships the 5-7 universal segments every store
needs at launch, plus 1-2 niche-specific segments per
niche, ready to push via ``SHOPIFY_CREATE_SEGMENT``.

Each segment carries:

  * ``name`` -- operator-readable handle
  * ``query`` -- ShopifyQL filter expression (string sent
    directly to ``segmentCreate``)
  * ``rationale`` -- one line for the operator on what
    this segment is for
  * ``engines`` -- list of existing engine names that
    consume this segment

The applier creates each segment via the existing
``SHOPIFY_CREATE_SEGMENT`` adapter and records per-segment
via Pattern Z so the autonomous loop sees per-segment
launch outcomes.

Return shape from :func:`generate_segment_pack`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "segments": [
            {
                "name": "VIPs",
                "query": "amount_spent > 500",
                "rationale": "Top spenders...",
                "engines": ["loyalty", "email_marketing"],
            },
            ...
        ],
    }
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Universal segments -- every store needs these.
# Each tuple: (name, query, rationale, engines).
#
# ShopifyQL syntax reference (subset used here):
#   amount_spent > N
#   number_of_orders >= N
#   last_order_date >= -Nd  (Shopify date-math)
#   email_subscription_status = 'SUBSCRIBED'
#   customer_account_status = 'ENABLED'
_UNIVERSAL_SEGMENTS: list[tuple[
    str, str, str, list[str],
]] = [
    (
        "VIPs",
        "amount_spent > 500",
        (
            "Top-spending customers -- prioritise for "
            "loyalty perks, white-glove support, and "
            "early-access drops."
        ),
        ["loyalty", "email_marketing", "wholesale_b2b"],
    ),
    (
        "Repeat Buyers",
        "number_of_orders >= 2",
        (
            "Bought twice or more -- the customers our "
            "store retention math is built around."
        ),
        ["loyalty", "churn_prediction", "email_marketing"],
    ),
    (
        "First-Time Buyers",
        "number_of_orders = 1",
        (
            "Single-order customers -- the cohort where "
            "second-purchase nudges (loyalty codes, "
            "thank-you series) have the highest leverage."
        ),
        ["loyalty", "email_marketing"],
    ),
    (
        "At-Risk (60d)",
        "last_order_date <= -60d AND number_of_orders >= 2",
        (
            "Repeat buyers who haven't ordered in 60+ "
            "days -- churn-prediction's primary input."
        ),
        ["churn_prediction", "email_marketing"],
    ),
    (
        "Lapsed (180d)",
        "last_order_date <= -180d",
        (
            "Hard-lapsed -- target with win-back campaign "
            "+ steep discount; expect lower conversion "
            "than at-risk but real signal when they "
            "respond."
        ),
        ["churn_prediction", "email_marketing"],
    ),
    (
        "Email Subscribers",
        "email_subscription_status = 'SUBSCRIBED'",
        (
            "Opted-in audience -- the only legal target "
            "for marketing emails. Most-leveraged "
            "marketing channel by LTV."
        ),
        ["email_marketing"],
    ),
    (
        "New This Month",
        "customer_added_date >= -30d",
        (
            "Customers who joined in the last 30 days -- "
            "the welcome funnel's primary cohort."
        ),
        ["email_marketing"],
    ),
]


# Niche-specific segments. Stack on top of the universal
# set so each niche gets ~9 total segments.
#
# Naming convention: stay short + operator-readable -- the
# segment list in Shopify admin gets cluttered fast.
_NICHE_SEGMENTS: dict[
    str, list[tuple[str, str, str, list[str]]],
] = {
    "beauty": [
        (
            "Skincare Buyers",
            "ordered_product_tag CONTAINS 'skincare'",
            (
                "Customers who bought from the skincare "
                "collection -- target with niche-specific "
                "education + cross-sells."
            ),
            ["email_marketing", "loyalty"],
        ),
        (
            "Subscription-Curious",
            "number_of_orders >= 3 "
            "AND last_order_date >= -45d",
            (
                "Engaged repeat buyers -- prime audience "
                "for a subscription pitch."
            ),
            ["email_marketing"],
        ),
    ],
    "fashion": [
        (
            "Seasonal Buyers",
            "last_order_date >= -90d "
            "AND number_of_orders = 1",
            (
                "Bought one piece in-season; target with "
                "complementary-piece recommendations "
                "before the next collection drops."
            ),
            ["email_marketing"],
        ),
        (
            "Sale Hunters",
            "ordered_product_tag CONTAINS 'sale'",
            (
                "Bought from the sale collection -- "
                "high price-elasticity; target with "
                "promo-led campaigns."
            ),
            ["email_marketing", "dynamic_pricing"],
        ),
    ],
    "tech": [
        (
            "Premium Tier",
            "amount_spent > 250",
            (
                "Tech-spend tier -- separate from "
                "general VIPs because tech AOV runs higher; "
                "target with new-product launches."
            ),
            ["email_marketing"],
        ),
        (
            "Cross-Sell Candidates",
            "ordered_product_tag CONTAINS 'audio' "
            "AND last_order_date >= -180d",
            (
                "Recent audio buyers -- accessories "
                "(cables, stands) are the natural "
                "cross-sell."
            ),
            ["email_marketing"],
        ),
    ],
    "home": [
        (
            "Project Buyers",
            "number_of_orders >= 3 "
            "AND amount_spent > 300",
            (
                "Customers building out a room / project "
                "-- target with curated room sets + "
                "designer-quality content."
            ),
            ["email_marketing"],
        ),
    ],
    "food": [
        (
            "Subscription Candidates",
            "number_of_orders >= 3 "
            "AND last_order_date >= -45d",
            (
                "Engaged repeat buyers in a category where "
                "subscription = higher LTV. Pitch the "
                "subscribe-and-save option."
            ),
            ["email_marketing"],
        ),
        (
            "Gift Buyers",
            "ordered_product_tag CONTAINS 'gift'",
            (
                "Bought a gift bundle -- target before "
                "holidays + birthdays with curated "
                "gift suggestions."
            ),
            ["email_marketing"],
        ),
    ],
    "pets": [
        (
            "Repeat-Food Buyers",
            "number_of_orders >= 2 "
            "AND ordered_product_tag CONTAINS 'food'",
            (
                "Bought pet food twice+ -- prime "
                "autoship / subscription audience."
            ),
            ["email_marketing", "loyalty"],
        ),
    ],
    "fitness": [
        (
            "Apparel Buyers",
            "ordered_product_tag CONTAINS 'apparel'",
            (
                "Bought apparel -- target with seasonal "
                "drops + size-matched recommendations."
            ),
            ["email_marketing"],
        ),
        (
            "Supplement Customers",
            "ordered_product_tag CONTAINS 'supplements' "
            "AND number_of_orders >= 2",
            (
                "Repeat-supplement buyers -- highest LTV "
                "category; pitch monthly subscription."
            ),
            ["email_marketing", "loyalty"],
        ),
    ],
    "jewelry": [
        (
            "High-Value Buyers",
            "amount_spent > 500",
            (
                "Jewelry's high AOV means VIP threshold "
                "matters per-category; this segment is "
                "the white-glove cohort."
            ),
            ["email_marketing", "loyalty"],
        ),
        (
            "Bridal Buyers",
            "ordered_product_tag CONTAINS 'bridal' "
            "OR ordered_product_tag CONTAINS 'engagement'",
            (
                "Bridal + engagement customers -- "
                "lifecycle marketing (anniversary, "
                "milestone) drives second purchases."
            ),
            ["email_marketing"],
        ),
    ],
    "outdoor": [
        (
            "Trail Apparel",
            "ordered_product_tag CONTAINS 'apparel'",
            (
                "Apparel buyers -- pitch related gear "
                "(packs, footwear) by trail type."
            ),
            ["email_marketing"],
        ),
    ],
    "baby": [
        (
            "Recent Parents",
            "customer_added_date >= -180d "
            "AND number_of_orders = 1",
            (
                "First-purchase parents in their first 6 "
                "months -- target with age-stage "
                "recommendations as their baby grows."
            ),
            ["email_marketing"],
        ),
        (
            "Gift Buyers",
            "ordered_product_tag CONTAINS 'gift'",
            (
                "Baby-shower / new-parent gift buyers -- "
                "different lifecycle than the parents "
                "themselves."
            ),
            ["email_marketing"],
        ),
    ],
    "general": [],
}


def generate_segment_pack(
    *,
    store_name: str,
    niche: str = "general",
) -> dict[str, Any]:
    """Build the structured segment specs for a niche.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general
            (universal-only).

    Returns:
        ``{store_name, niche, segments: [...]}``. The
        segments list always carries the universal 7
        plus the niche-specific entries.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    niche_entries = _NICHE_SEGMENTS.get(niche_n, [])

    segments: list[dict[str, Any]] = []
    for entry in _UNIVERSAL_SEGMENTS + niche_entries:
        segment_name, query, rationale, engines = entry
        segments.append({
            "name": segment_name,
            "query": query,
            "rationale": rationale,
            "engines": list(engines),
        })

    return {
        "store_name": name,
        "niche": niche_n,
        "segments": segments,
    }


def apply_segment_pack(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push each segment spec via SHOPIFY_CREATE_SEGMENT.

    Args:
        spec: Dict from :func:`generate_segment_pack`.
        store_id: Optional per-store Pattern Z scope.

    Returns:
        ``{applied_count, results}``. Each result:
        ``{name, ok, error, segment_id}``.
    """
    if not isinstance(spec, dict):
        return {"applied_count": 0, "results": []}
    segments = spec.get("segments") or []
    if not isinstance(segments, list) or not segments:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "name": s.get("name", ""),
                "ok": False,
                "error": "router_unavailable",
                "segment_id": None,
            }
            for s in segments
        ]
        for r in results:
            _record(
                name=r["name"], success=False,
                error="router_unavailable",
                store_id=store_id,
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied = 0
    for segment in segments:
        seg_name = segment.get("name", "")
        seg_query = segment.get("query", "")
        if not seg_name or not seg_query:
            results.append({
                "name": seg_name,
                "ok": False,
                "error": "missing_name_or_query",
                "segment_id": None,
            })
            continue
        params = {"name": seg_name, "query": seg_query}
        try:
            res = router.execute(capability, params)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "customer_segments raised for %s: %s",
                seg_name, exc,
            )
            results.append({
                "name": seg_name,
                "ok": False,
                "error": f"adapter_raise: {exc}",
                "segment_id": None,
            })
            _record(
                name=seg_name, success=False,
                error=str(exc), store_id=store_id,
            )
            continue
        ok = bool(getattr(res, "ok", False))
        err = getattr(res, "error", None)
        segment_id = None
        if ok:
            data = getattr(res, "data", {}) or {}
            seg_payload = data.get("segment") or {}
            segment_id = seg_payload.get("id")
            applied += 1
        results.append({
            "name": seg_name,
            "ok": ok,
            "error": (
                None if ok else str(err or "rejected")
            ),
            "segment_id": segment_id,
        })
        _record(
            name=seg_name, success=ok,
            error=None if ok else str(err or "rejected"),
            store_id=store_id,
        )

    return {"applied_count": applied, "results": results}


# ── Helpers ───────────────────────────────────────────────────


def _record(
    *,
    name: str,
    success: bool,
    error: str | None,
    store_id: str | None,
) -> None:
    params: dict[str, Any] = {"segment_name": name}
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_customer_segment",
            capability="SHOPIFY_CREATE_SEGMENT",
            params=params,
            success=bool(success),
            error=error,
            metrics={"segment_name": name},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_segments record_writeback raised: "
            "%s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_segments router import failed: %s",
            exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_SEGMENT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_segments capability resolve failed: "
            "%s", exc,
        )
        return None
