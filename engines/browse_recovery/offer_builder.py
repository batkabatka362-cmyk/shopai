"""Browse Recovery Engine — offer builder.

Builds personalized recovery offers based on intent score,
viewed products, and engagement signals. Matches offer aggressiveness
to purchase likelihood.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Offer tiers by intent level
# ---------------------------------------------------------------------------

_OFFER_TIERS: dict[str, dict[str, Any]] = {
    "high": {
        "offer_type": "gentle_reminder",
        "discount_pct": 5.0,
        "urgency": "low",
    },
    "medium": {
        "offer_type": "incentive",
        "discount_pct": 10.0,
        "urgency": "medium",
    },
    "low": {
        "offer_type": "aggressive_discount",
        "discount_pct": 20.0,
        "urgency": "high",
    },
}


def build_offers(
    intent_scores: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build personalized recovery offers for each target.

    Args:
        intent_scores: List of IntentScore dicts from intent_scorer.
        sessions: Original session data for product context.
        products: Full product catalog for matching.

    Returns:
        Structured dict with per-user recovery offers.
    """
    try:
        score_items = copy.deepcopy(intent_scores)
        session_map: dict[str, dict[str, Any]] = {}
        for s in sessions:
            uid = str(s.get("user_id", ""))
            session_map[uid] = s

        product_map: dict[str, dict[str, Any]] = {}
        for p in products:
            pid = str(p.get("id", ""))
            product_map[pid] = p

        offers: list[dict[str, Any]] = []

        for score_item in score_items:
            user_id = str(score_item.get("user_id", "unknown"))
            likelihood = str(score_item.get("purchase_likelihood", "low"))
            intent = float(score_item.get("intent_score", 0.0))

            tier = _OFFER_TIERS.get(likelihood, _OFFER_TIERS["low"])

            # Get viewed products from session
            session = session_map.get(user_id, {})
            viewed = session.get("products_viewed", [])
            featured = viewed[:3] if viewed else []

            # Build personalized message
            product_names = []
            for pid in featured:
                prod = product_map.get(str(pid), {})
                name = prod.get("title", str(pid))
                product_names.append(name)

            if product_names:
                items_text = ", ".join(product_names)
                message = (
                    f"Still interested in {items_text}? "
                    f"Get {tier['discount_pct']:.0f}% off today."
                )
            else:
                message = (
                    f"Come back and save {tier['discount_pct']:.0f}% "
                    f"on items you were browsing."
                )

            offers.append({
                "user_id": user_id,
                "offer_type": tier["offer_type"],
                "discount_pct": tier["discount_pct"],
                "featured_products": featured,
                "message": message,
                "urgency": tier["urgency"],
            })

        return {
            "status": "success",
            "offers": offers,
        }
    except Exception as exc:
        return {
            "status": "error",
            "offers": [],
            "error": f"Offer building failed: {exc}",
        }
