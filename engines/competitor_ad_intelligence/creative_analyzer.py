"""Competitor Ad Intelligence Engine — creative analyzer.

Analyzes ad creative patterns across competitors.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def analyze_creatives(
    ads_detected: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze creative patterns from detected competitor ads.

    Args:
        ads_detected: Detected ads with type and creative info.

    Returns:
        Structured dict with creative patterns.
    """
    try:
        # Count ad types per competitor
        comp_types: dict[str, dict[str, int]] = {}
        for ad in ads_detected:
            comp = ad.get("competitor", "")
            ad_type = ad.get("ad_type", "unknown")
            comp_types.setdefault(comp, {}).setdefault(ad_type, 0)
            comp_types[comp][ad_type] += 1

        patterns: list[dict[str, Any]] = []
        for comp, types in comp_types.items():
            for ad_type, count in types.items():
                if ad_type == "unknown":
                    continue
                if count >= 3:
                    desc = f"Heavy use of {ad_type} ads ({count} detected)"
                elif count >= 1:
                    desc = f"Uses {ad_type} ads ({count} detected)"
                else:
                    continue

                patterns.append({
                    "competitor": comp,
                    "pattern_type": ad_type,
                    "frequency": count,
                    "description": desc,
                })

        return {"status": "success", "creative_patterns": patterns}
    except Exception as exc:
        return {"status": "error", "creative_patterns": [], "error": f"Creative analysis failed: {exc}"}
