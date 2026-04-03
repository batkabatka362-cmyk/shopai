"""User Tracking Engine — attribution tracker.

Tracks conversion attribution across channels using
last-touch and linear attribution models.
"""
from __future__ import annotations

import copy
from typing import Any


def track_attribution(
    journeys: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track conversion attribution across channels.

    Args:
        journeys: Mapped customer journeys.

    Returns:
        Structured dict with attribution results.
    """
    try:
        data = copy.deepcopy(journeys)

        last_touch: dict[str, int] = {}
        linear: dict[str, float] = {}
        total_conversions = 0

        for journey in data:
            if not journey.get("converted", False):
                continue

            total_conversions += 1
            steps = journey.get("steps", [])
            channels_in_journey: list[str] = []

            for step in steps:
                channel = step.get("channel", "unknown")
                channels_in_journey.append(channel)

            if not channels_in_journey:
                continue

            # Last-touch attribution
            last_channel = channels_in_journey[-1]
            last_touch[last_channel] = last_touch.get(last_channel, 0) + 1

            # Linear attribution: equal credit
            unique_channels = list(dict.fromkeys(channels_in_journey))
            credit = 1.0 / len(unique_channels) if unique_channels else 0.0
            for ch in unique_channels:
                linear[ch] = linear.get(ch, 0.0) + credit

        attribution: list[dict[str, Any]] = []

        all_channels = set(last_touch.keys()) | set(linear.keys())
        for channel in sorted(all_channels):
            lt_count = last_touch.get(channel, 0)
            lin_credit = linear.get(channel, 0.0)

            lt_pct = round(lt_count / total_conversions * 100, 1) if total_conversions > 0 else 0.0
            lin_pct = round(lin_credit / total_conversions * 100, 1) if total_conversions > 0 else 0.0

            attribution.append({
                "channel": channel,
                "model": "last_touch",
                "attribution_pct": lt_pct,
                "conversions": lt_count,
            })
            attribution.append({
                "channel": channel,
                "model": "linear",
                "attribution_pct": lin_pct,
                "conversions": round(lin_credit, 2),
            })

        return {
            "status": "success",
            "attribution": attribution,
            "total_conversions": total_conversions,
        }
    except Exception as exc:
        return {
            "status": "error",
            "attribution": [],
            "error": f"Attribution tracking failed: {exc}",
        }
