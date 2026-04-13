"""Gift Card Engine — redemption tracker.

Tracks redemption patterns: frequency, average redemption value,
time-to-redeem, and partial vs full redemptions.
"""
from __future__ import annotations

import copy
from typing import Any


def track_redemptions(
    redemptions: list[dict[str, Any]],
    gift_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track redemption patterns.

    Args:
        redemptions: Redemption transaction records.
        gift_cards: Gift card records.

    Returns:
        Structured dict with redemption tracking data.
    """
    try:
        redems = copy.deepcopy(redemptions)

        total_redemptions = len(redems)
        total_redeemed_value = sum(float(r.get("amount", 0)) for r in redems)

        if total_redemptions == 0:
            return {
                "status": "success",
                "redemption_stats": {
                    "total_redemptions": 0,
                    "total_redeemed_value": 0.0,
                    "avg_redemption_value": 0.0,
                    "partial_redemption_pct": 0.0,
                },
            }

        avg_redemption = round(total_redeemed_value / total_redemptions, 2)

        # Partial vs full redemptions
        partial = sum(1 for r in redems if r.get("is_partial", False))
        partial_pct = round(partial / total_redemptions * 100, 1)

        # Redemption by channel
        by_channel: dict[str, int] = {}
        for r in redems:
            channel = str(r.get("channel", "online"))
            by_channel[channel] = by_channel.get(channel, 0) + 1

        return {
            "status": "success",
            "redemption_stats": {
                "total_redemptions": total_redemptions,
                "total_redeemed_value": round(total_redeemed_value, 2),
                "avg_redemption_value": avg_redemption,
                "partial_redemption_pct": partial_pct,
                "by_channel": by_channel,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "redemption_stats": {},
            "error": f"Redemption tracking failed: {exc}",
        }
