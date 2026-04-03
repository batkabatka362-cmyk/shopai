"""Behavioral Data Engine — heatmap builder.

Builds interaction heatmaps from user events: which elements
get the most interaction, intensity mapping, and hot zones.
"""
from __future__ import annotations

import copy
from typing import Any


def build_heatmaps(
    events: list[dict[str, Any]],
    product_views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build interaction heatmaps from events.

    Args:
        events: User interaction events.
        product_views: Product view events.

    Returns:
        Structured dict with heatmap cells and hot zones.
    """
    try:
        all_events = copy.deepcopy(events) + copy.deepcopy(product_views)

        # Count interactions per element/page
        element_counts: dict[str, int] = {}

        for event in all_events:
            element = str(
                event.get("element")
                or event.get("page")
                or event.get("product_id")
                or event.get("type", "unknown")
            )
            element_counts[element] = element_counts.get(element, 0) + 1

        if not element_counts:
            return {
                "status": "success",
                "heatmap": [],
                "hot_zones": [],
                "total_interactions": 0,
            }

        max_count = max(element_counts.values())

        cells: list[dict[str, Any]] = []
        for element, count in sorted(
            element_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            intensity = round(count / max_count, 3) if max_count > 0 else 0.0
            cells.append({
                "element": element,
                "interaction_count": count,
                "intensity": intensity,
            })

        # Hot zones: top 20% by intensity
        cutoff = max(1, len(cells) // 5)
        hot_zones = [c["element"] for c in cells[:cutoff]]

        total_interactions = sum(element_counts.values())

        return {
            "status": "success",
            "heatmap": cells,
            "hot_zones": hot_zones,
            "total_interactions": total_interactions,
        }
    except Exception as exc:
        return {
            "status": "error",
            "heatmap": [],
            "error": f"Heatmap building failed: {exc}",
        }
