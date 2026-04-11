"""Brand Positioning Engine — gap analyzer.

Finds positioning gaps in the market by analyzing which
price/quality quadrants are underserved by competitors.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


_ALL_QUADRANTS = [
    "Premium (High Price, High Quality)",
    "Value (Low Price, High Quality)",
    "Overpriced (High Price, Low Quality)",
    "Economy (Low Price, Low Quality)",
]


def analyze_gaps(
    position_map: dict[str, Any],
) -> dict[str, Any]:
    """Find positioning gaps in the market.

    Args:
        position_map: Position map dict with entries.

    Returns:
        Structured dict with market gaps.
    """
    try:
        entries = position_map.get("entries", [])

        # Count competitors per quadrant (exclude first entry = brand)
        quadrant_counts: dict[str, int] = {q: 0 for q in _ALL_QUADRANTS}
        for entry in entries[1:]:  # Skip brand (first entry)
            quadrant = str(entry.get("quadrant", ""))
            if quadrant in quadrant_counts:
                quadrant_counts[quadrant] += 1

        total_competitors = max(len(entries) - 1, 1)
        gaps: list[dict[str, Any]] = []

        for quadrant in _ALL_QUADRANTS:
            count = quadrant_counts.get(quadrant, 0)
            saturation = count / total_competitors

            if saturation < 0.25:
                opportunity_score = round((1.0 - saturation) * 100, 1)
                if count == 0:
                    desc = f"No competitors in the {quadrant} quadrant — wide open opportunity"
                else:
                    desc = f"Only {count} competitor(s) in {quadrant} — underserved segment"

                # Deprioritize "Overpriced" quadrant — it is inherently weak
                if "Overpriced" in quadrant:
                    opportunity_score = max(opportunity_score - 30, 0)
                    desc += " (note: this quadrant is inherently risky)"

                gaps.append({
                    "quadrant": quadrant,
                    "description": desc,
                    "opportunity_score": opportunity_score,
                })

        # Sort by opportunity score descending
        gaps.sort(key=lambda g: g["opportunity_score"], reverse=True)

        return {
            "status": "success",
            "gaps": gaps,
        }
    except Exception as exc:
        return {
            "status": "error",
            "gaps": [],
            "error": f"Gap analysis failed: {exc}",
        }
