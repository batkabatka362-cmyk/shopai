"""Brand Positioning Engine — differentiation scorer.

Scores brand differentiation from each competitor based on
price distance, quality distance, and positioning overlap.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import math
from typing import Any


def score_differentiation(
    position_map: dict[str, Any],
    brand: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score differentiation from each competitor.

    Args:
        position_map: Position map dict with entries.
        brand: Brand info dict with values.
        competitors: List of competitor dicts.

    Returns:
        Structured dict with differentiation scores.
    """
    try:
        entries = position_map.get("entries", [])
        if not entries:
            return {"status": "success", "differentiation_scores": []}

        brand_entry = entries[0]
        brand_price = float(brand_entry.get("price_score", 5.0))
        brand_quality = float(brand_entry.get("quality_score", 5.0))
        brand_values = set(
            v.lower() for v in brand.get("values", [])
        )

        scores: list[dict[str, Any]] = []

        for i, comp_entry in enumerate(entries[1:]):
            comp_price = float(comp_entry.get("price_score", 5.0))
            comp_quality = float(comp_entry.get("quality_score", 5.0))

            # Euclidean distance on the price/quality grid (max ~14.1)
            distance = math.sqrt(
                (brand_price - comp_price) ** 2
                + (brand_quality - comp_quality) ** 2
            )
            # Normalize to 0-100 scale
            diff_score = round(min(distance / 14.14 * 100, 100), 1)

            # Determine shared traits and unique advantages
            comp_data = competitors[i] if i < len(competitors) else {}
            comp_positioning = str(comp_data.get("positioning", "")).lower()

            shared_traits: list[str] = []
            unique_advantages: list[str] = []

            if abs(brand_price - comp_price) < 2:
                shared_traits.append("similar price range")
            else:
                if brand_price < comp_price:
                    unique_advantages.append("more affordable pricing")
                else:
                    unique_advantages.append("premium positioning justifies higher price")

            if abs(brand_quality - comp_quality) < 2:
                shared_traits.append("comparable quality perception")
            else:
                if brand_quality > comp_quality:
                    unique_advantages.append("higher perceived quality")
                else:
                    shared_traits.append("competitor has quality edge")

            if brand_entry.get("quadrant") == comp_entry.get("quadrant"):
                shared_traits.append("same market quadrant — direct competitor")
            else:
                unique_advantages.append("occupies different market quadrant")

            # Check value overlap
            for value in brand_values:
                if value in comp_positioning:
                    shared_traits.append(f"both emphasize {value}")

            if not shared_traits:
                shared_traits.append("minimal overlap")
            if not unique_advantages:
                unique_advantages.append("differentiation opportunity exists")

            scores.append({
                "competitor_name": str(comp_entry.get("name", "Unknown")),
                "differentiation_score": diff_score,
                "shared_traits": shared_traits,
                "unique_advantages": unique_advantages,
            })

        return {
            "status": "success",
            "differentiation_scores": scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "differentiation_scores": [],
            "error": f"Differentiation scoring failed: {exc}",
        }
