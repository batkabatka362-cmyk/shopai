"""Search volume domain knowledge — expert heuristics and benchmarks.

What experienced e-commerce marketers know about search volume and demand:
  - "Search volume = demand ceiling, not demand floor"
  - "Long-tail keywords convert 2.5x better than head terms"
  - "Amazon search volume ~ Google x 0.7 for product searches"
  - "A keyword with 500 searches and 5% conversion > 50K with 0.01%"
"""
from __future__ import annotations

from typing import Any


HEURISTICS: list[str] = [
    "Search volume = demand ceiling, not demand floor. Actual addressable demand is "
    "always lower due to competition, intent mismatch, and conversion loss.",
    "Long-tail keywords convert 2.5x better than head terms. 'waterproof hiking boots "
    "for wide feet' beats 'hiking boots' for a niche store.",
    "Amazon search volume is approximately Google x 0.7 for product searches. Amazon "
    "captures high-intent buyers directly, bypassing Google.",
    "Transactional keywords ('buy X', 'X price', 'cheap X') convert 3-5x better than "
    "informational keywords ('what is X', 'how to X').",
    "A keyword needs at least 200 monthly searches to be worth targeting as a primary "
    "keyword. Below that, aggregate multiple long-tail variants.",
    "Search volume trending downward for 3+ months signals declining demand — "
    "enter with caution or find a rising alternative.",
    "Seasonal spikes can inflate demand estimates by 2-3x. Always normalize to "
    "12-month averages before making product decisions.",
    "The top 3 organic results capture 55% of all clicks. If you cannot rank in "
    "the top 5, paid search is your primary channel.",
    "Search volume fragmentation: the primary keyword often represents only 20-30% "
    "of total related search demand. Always aggregate related terms.",
]

# Platform-specific search volume multipliers (relative to Google)
PLATFORM_MULTIPLIERS: dict[str, dict[str, Any]] = {
    "amazon":    {"multiplier": 0.70, "note": "~70% of Google product search volume", "intent_quality": "very_high"},
    "google":    {"multiplier": 1.00, "note": "Baseline — most tools report Google volume", "intent_quality": "mixed"},
    "youtube":   {"multiplier": 0.15, "note": "Video searches — informational, low conversion", "intent_quality": "low"},
    "pinterest": {"multiplier": 0.10, "note": "Visual discovery — good for fashion/home/food", "intent_quality": "medium"},
    "tiktok":    {"multiplier": 0.08, "note": "Rising search platform — trend-driven", "intent_quality": "low"},
}

# Strategic guidance by volume tier
VOLUME_INTERPRETATION: dict[str, dict[str, str]] = {
    "mega": {
        "range": "100K+",
        "strategy": "Do NOT target head term directly. Focus on long-tail variants.",
        "recommended_approach": "long-tail SEO + paid search on specific variants",
    },
    "high": {
        "range": "10K-100K",
        "strategy": "Viable primary keyword if competition allows. Build content cluster.",
        "recommended_approach": "content marketing + targeted paid search",
    },
    "medium": {
        "range": "1K-10K",
        "strategy": "Sweet spot for niche stores. Enough volume, rankable in 6-12 months.",
        "recommended_approach": "SEO-first with supplemental paid search",
    },
    "low": {
        "range": "200-1K",
        "strategy": "Viable only with high conversion or 10+ aggregated long-tail keywords.",
        "recommended_approach": "aggregate keywords, content depth strategy",
    },
}


def get_heuristics() -> list[str]:
    """Return expert heuristics for search volume interpretation."""
    return HEURISTICS


def get_search_insight(volume_tier: str) -> dict[str, str]:
    """Get strategic guidance for a given search volume tier."""
    return VOLUME_INTERPRETATION.get(volume_tier, VOLUME_INTERPRETATION["medium"])


def get_platform_multiplier(platform: str) -> dict[str, Any]:
    """Get search volume multiplier and context for a platform."""
    return PLATFORM_MULTIPLIERS.get(
        platform.lower(),
        {"multiplier": 1.0, "note": "Unknown platform", "intent_quality": "unknown"},
    )


def estimate_total_search_demand(
    google_volume: int, include_platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Estimate total search demand across platforms from Google baseline."""
    platforms = include_platforms or ["amazon", "pinterest"]
    total = google_volume
    breakdown: dict[str, int] = {"google": google_volume}

    for platform in platforms:
        info = PLATFORM_MULTIPLIERS.get(platform.lower())
        if info:
            plat_volume = int(google_volume * info["multiplier"])
            breakdown[platform] = plat_volume
            total += plat_volume

    return {
        "total_estimated_searches": total,
        "breakdown": breakdown,
        "note": "Estimates based on platform multipliers relative to Google volume",
    }
