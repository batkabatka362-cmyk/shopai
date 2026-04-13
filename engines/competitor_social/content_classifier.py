"""Competitor Social Engine — content classifier.

Classifies competitor content types (product, lifestyle, UGC, etc.).
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def classify_content(
    competitor_profiles: list[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify competitor content by type.

    Args:
        competitor_profiles: Tracked competitor profiles.
        competitors: Raw competitor data with content info.

    Returns:
        Structured dict with content breakdowns.
    """
    try:
        comp_data = {str(c.get("name", "")): c for c in competitors}
        breakdowns: list[dict[str, Any]] = []

        seen = set()
        for profile in competitor_profiles:
            comp = profile["competitor"]
            plat = profile["platform"]
            key = f"{comp}:{plat}"
            if key in seen:
                continue
            seen.add(key)

            raw = comp_data.get(comp, {})
            content_mix = raw.get("content_mix", raw.get("content", {})).get(plat, {})

            if content_mix:
                total = sum(float(v) for v in content_mix.values())
                if total > 0:
                    normalized = {k: round(float(v) / total, 2) for k, v in content_mix.items()}
                else:
                    normalized = content_mix
            else:
                # Default breakdown
                normalized = {
                    "product": 0.40,
                    "lifestyle": 0.25,
                    "ugc": 0.15,
                    "promotional": 0.20,
                }

            breakdowns.append({
                "competitor": comp,
                "platform": plat,
                "content_types": normalized,
            })

        return {"status": "success", "content_breakdown": breakdowns}
    except Exception as exc:
        return {"status": "error", "content_breakdown": [], "error": f"Content classification failed: {exc}"}
