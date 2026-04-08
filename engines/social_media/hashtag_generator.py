"""Social Media Engine — hashtag generator.

Generates relevant hashtags for each platform: trending, niche, branded,
and provides volume-based ranking.  Respects per-platform hashtag limits.

Model note: no model usage — deterministic hashtag strategy.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Hashtag pools
# ---------------------------------------------------------------------------

_TRENDING_HASHTAGS: dict[str, list[str]] = {
    "instagram": [
        "#instagood", "#photooftheday", "#reels", "#explorepage",
        "#trending", "#viral", "#instadaily", "#fyp",
    ],
    "facebook": [
        "#facebook", "#facebooklive", "#community", "#share",
        "#trending", "#viral",
    ],
    "tiktok": [
        "#fyp", "#foryoupage", "#viral", "#trending",
        "#tiktok", "#tiktokmademebuyit",
    ],
    "pinterest": [
        "#pinterest", "#pinterestinspired", "#pinterestfinds",
        "#aesthetic", "#homedecor", "#diy",
    ],
    "twitter": [
        "#trending", "#viral", "#thread",
    ],
}

_NICHE_HASHTAGS: dict[str, list[str]] = {
    "fashion": ["#ootd", "#fashioninspo", "#streetstyle", "#outfitideas", "#styleinspo"],
    "beauty": ["#beautytips", "#skincare", "#makeuplover", "#beautyinspo", "#glowup"],
    "tech": ["#techreview", "#gadgets", "#innovation", "#futuretech", "#unboxing"],
    "food": ["#foodie", "#homecooking", "#recipe", "#foodphotography", "#yummy"],
    "fitness": ["#fitfam", "#workout", "#gymlife", "#healthylifestyle", "#motivation"],
    "home": ["#homedecor", "#interiordesign", "#homestyle", "#cozy", "#organization"],
    "general": ["#shopnow", "#newdrop", "#musthave", "#bestoftheday", "#recommended"],
}

_GOAL_HASHTAGS: dict[str, list[str]] = {
    "engagement": ["#comment", "#tagafriend", "#letschat", "#yourturn", "#tellus"],
    "awareness": ["#newlaunch", "#discover", "#brandnew", "#introducing", "#comingsoon"],
    "traffic": ["#linkinbio", "#shopnow", "#clickthelink", "#availablenow", "#getshopping"],
    "conversions": ["#limitedoffer", "#sale", "#dealoftheday", "#flashsale", "#buynoworcrylater"],
}


# ---------------------------------------------------------------------------
# Volume scoring (placeholder — awaits real trends adapter)
#
# Previously this module shipped a 20-entry ``_VOLUME_SCORES`` dict
# with hand-picked decimal scores (``"#fyp": 0.99``, ``"#viral":
# 0.95``, ...) and a ``_DEFAULT_VOLUME`` of ``0.40`` for anything
# not in the dict. Downstream ranking then sorted hashtags by
# those fake scores and treated the top entries as "trending",
# when in reality the values came from nowhere. Real trend data
# will be pulled from a Google Trends / Exploding Topics adapter
# — until then every tag receives ``volume_score = None`` so the
# caller can tell the source is missing instead of trusting a
# made-up decimal.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_hashtags(
    platforms: list[str],
    products: list[dict[str, Any]],
    brand: dict[str, Any],
    goal: str,
    platform_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate hashtag sets for each platform.

    Args:
        platforms: Target platforms.
        products: Product list for niche detection.
        brand: Brand info dict.
        goal: Campaign goal.
        platform_analyses: Per-platform analysis data (for hashtag limits).

    Returns:
        Structured dict with per-platform hashtag sets.
    """
    try:
        platforms = copy.deepcopy(platforms)
        brand_name = str(brand.get("name", "brand")).strip().lower().replace(" ", "")

        # Detect primary category from products
        category = _detect_category(products)
        goal_tags = _GOAL_HASHTAGS.get(goal, [])

        hashtag_sets: list[dict[str, Any]] = []

        for platform_name in platforms:
            name = str(platform_name).lower().strip()

            # Determine hashtag limit from analysis
            limit = _get_hashtag_limit(platform_analyses, name)

            # Trending hashtags for this platform
            trending = list(_TRENDING_HASHTAGS.get(name, []))

            # Niche hashtags based on product category
            niche = list(_NICHE_HASHTAGS.get(category, _NICHE_HASHTAGS["general"]))

            # Branded hashtags
            branded = [
                f"#{brand_name}",
                f"#{brand_name}style",
                f"#{brand_name}official",
            ]

            # Combine and rank all tags by volume
            all_tags = list(set(trending + niche + goal_tags + branded))
            ranked = _rank_by_volume(all_tags)

            # Trim to platform limit
            ranked = ranked[:limit]
            trending = [t for t in trending if t in {r["tag"] for r in ranked}]
            niche = [t for t in niche if t in {r["tag"] for r in ranked}]
            branded = [t for t in branded if t in {r["tag"] for r in ranked}]

            hashtag_set: dict[str, Any] = {
                "platform": name,
                "trending": trending,
                "niche": niche,
                "branded": branded,
                "ranked": ranked,
            }
            hashtag_sets.append(hashtag_set)

        return {
            "status": "success",
            "hashtag_sets": hashtag_sets,
        }
    except Exception as exc:
        return {
            "status": "error",
            "hashtag_sets": [],
            "error": f"Hashtag generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_category(products: list[dict[str, Any]]) -> str:
    """Detect the dominant product category."""
    if not products:
        return "general"

    categories: dict[str, int] = {}
    for p in products:
        cat = str(p.get("category", "general")).lower().strip()
        categories[cat] = categories.get(cat, 0) + 1

    best = max(categories, key=categories.get)  # type: ignore[arg-type]
    return best if best in _NICHE_HASHTAGS else "general"


def _get_hashtag_limit(
    analyses: list[dict[str, Any]],
    platform: str,
) -> int:
    """Get the hashtag limit for a platform from analysis data."""
    for a in analyses:
        if a.get("platform") == platform:
            return int(a.get("hashtag_limit", 10))
    return 10


def _rank_by_volume(tags: list[str]) -> list[dict[str, Any]]:
    """Return tags as a flat list with ``volume_score = None``.

    Pre-cleanup this sorted tags by a hand-picked fake decimal
    score from ``_VOLUME_SCORES`` (``#fyp: 0.99``, ``#viral:
    0.95``, ...) and a ``0.40`` default. The scores came from
    nowhere and corrupted any caller that trusted the ordering.
    The real trend data will arrive via a Google Trends /
    Exploding Topics adapter; until then every entry carries
    ``volume_score = None`` and tags stay in insertion order so
    the caller can detect the missing signal.
    """
    return [{"tag": tag, "volume_score": None} for tag in tags]
