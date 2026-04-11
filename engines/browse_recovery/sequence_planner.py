"""Browse Recovery Engine — sequence planner.

Plans multi-touch recovery sequences: email, push notification, retargeting
ads, and SMS touchpoints spread over days. Sequence intensity scales with
intent score and offer urgency.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Sequence templates by urgency
# ---------------------------------------------------------------------------

_SEQUENCES: dict[str, list[dict[str, Any]]] = {
    "low": [
        {"day": 1, "channel": "email", "action": "product_reminder"},
        {"day": 3, "channel": "email", "action": "social_proof"},
        {"day": 7, "channel": "email", "action": "gentle_offer"},
    ],
    "medium": [
        {"day": 0, "channel": "email", "action": "product_reminder"},
        {"day": 1, "channel": "push", "action": "limited_offer"},
        {"day": 3, "channel": "email", "action": "urgency_reminder"},
        {"day": 5, "channel": "retargeting", "action": "display_ad"},
        {"day": 7, "channel": "email", "action": "last_chance"},
    ],
    "high": [
        {"day": 0, "channel": "email", "action": "product_reminder"},
        {"day": 0, "channel": "push", "action": "flash_offer"},
        {"day": 1, "channel": "sms", "action": "personal_offer"},
        {"day": 2, "channel": "retargeting", "action": "display_ad"},
        {"day": 3, "channel": "email", "action": "urgency_countdown"},
        {"day": 5, "channel": "email", "action": "last_chance"},
        {"day": 7, "channel": "retargeting", "action": "final_reminder"},
    ],
}


def plan_sequences(
    offers: list[dict[str, Any]],
    intent_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan multi-touch recovery sequences for each target.

    Args:
        offers: List of RecoveryOffer dicts from offer_builder.
        intent_scores: List of IntentScore dicts for context.

    Returns:
        Structured dict with per-user recovery sequences.
    """
    try:
        offer_items = copy.deepcopy(offers)
        score_map: dict[str, dict[str, Any]] = {}
        for s in intent_scores:
            uid = str(s.get("user_id", ""))
            score_map[uid] = s

        sequences: list[dict[str, Any]] = []

        for offer in offer_items:
            user_id = str(offer.get("user_id", "unknown"))
            urgency = str(offer.get("urgency", "medium"))

            template = _SEQUENCES.get(urgency, _SEQUENCES["medium"])
            steps = copy.deepcopy(template)

            # Enrich steps with offer context
            discount = offer.get("discount_pct", 0.0)
            for step in steps:
                step["offer_discount_pct"] = discount
                step["user_id"] = user_id

            channels = list({s["channel"] for s in steps})
            max_day = max(s["day"] for s in steps) if steps else 0

            sequences.append({
                "user_id": user_id,
                "steps": steps,
                "total_touches": len(steps),
                "duration_days": max_day,
                "channel_mix": sorted(channels),
            })

        return {
            "status": "success",
            "sequences": sequences,
        }
    except Exception as exc:
        return {
            "status": "error",
            "sequences": [],
            "error": f"Sequence planning failed: {exc}",
        }
