"""Demand Analysis Engine — segment decomposer.

Decompose demand by segment (geography, channel, customer type).
"""
from __future__ import annotations

import copy
from typing import Any


def decompose_segments(
    **kwargs: Any,
) -> dict[str, Any]:
    """Decompose demand by segment.

    Args:
        **kwargs: Must include 'segments' list and volume data.

    Returns:
        Structured dict with segment breakdown.
    """
    try:
        segments = copy.deepcopy(kwargs.get("segments", []))
        vol_data = kwargs.get("volume_estimator_data", {})
        total_volume = int(vol_data.get("total_market_volume", 0))

        segment_results: list[dict[str, Any]] = []

        for seg in segments:
            name = str(seg.get("name", "unknown"))
            volume = int(seg.get("volume", 0))
            share = round(volume / max(total_volume, 1) * 100, 1)
            growth = float(seg.get("growth_rate", 0))

            segment_results.append({
                "name": name,
                "volume": volume,
                "share_pct": share,
                "growth_rate": growth,
                "size_rank": 0,  # Will be set below
            })

        # Rank by volume
        segment_results.sort(key=lambda s: s["volume"], reverse=True)
        for i, seg in enumerate(segment_results):
            seg["size_rank"] = i + 1

        return {
            "status": "success",
            "result": {"segments": segment_results},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Segment decomposition failed: {exc}"}
