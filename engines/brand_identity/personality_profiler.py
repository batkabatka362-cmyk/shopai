"""Brand Identity Engine — personality profiler.

Defines brand personality: archetype, traits, tone keywords,
and emotional appeal based on business category and target audience.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Archetype mappings by category keywords
# ---------------------------------------------------------------------------

_ARCHETYPE_MAP: dict[str, dict[str, Any]] = {
    "luxury": {
        "archetype": "The Ruler",
        "traits": ["sophisticated", "exclusive", "authoritative", "refined"],
        "tone_keywords": ["elegant", "premium", "distinguished"],
        "emotional_appeal": "aspiration and status",
    },
    "tech": {
        "archetype": "The Magician",
        "traits": ["innovative", "visionary", "transformative", "smart"],
        "tone_keywords": ["cutting-edge", "seamless", "empowering"],
        "emotional_appeal": "possibility and transformation",
    },
    "outdoor": {
        "archetype": "The Explorer",
        "traits": ["adventurous", "rugged", "independent", "bold"],
        "tone_keywords": ["fearless", "authentic", "wild"],
        "emotional_appeal": "freedom and discovery",
    },
    "health": {
        "archetype": "The Caregiver",
        "traits": ["nurturing", "trustworthy", "compassionate", "reliable"],
        "tone_keywords": ["gentle", "supportive", "wholesome"],
        "emotional_appeal": "safety and well-being",
    },
    "fashion": {
        "archetype": "The Lover",
        "traits": ["passionate", "sensual", "expressive", "stylish"],
        "tone_keywords": ["alluring", "bold", "confident"],
        "emotional_appeal": "beauty and connection",
    },
    "food": {
        "archetype": "The Everyman",
        "traits": ["approachable", "honest", "warm", "relatable"],
        "tone_keywords": ["homey", "genuine", "comforting"],
        "emotional_appeal": "belonging and comfort",
    },
    "fitness": {
        "archetype": "The Hero",
        "traits": ["determined", "courageous", "disciplined", "inspiring"],
        "tone_keywords": ["powerful", "motivating", "strong"],
        "emotional_appeal": "achievement and mastery",
    },
    "kids": {
        "archetype": "The Innocent",
        "traits": ["playful", "optimistic", "joyful", "simple"],
        "tone_keywords": ["fun", "bright", "cheerful"],
        "emotional_appeal": "happiness and simplicity",
    },
    "creative": {
        "archetype": "The Creator",
        "traits": ["imaginative", "artistic", "expressive", "original"],
        "tone_keywords": ["inspiring", "unique", "visionary"],
        "emotional_appeal": "self-expression and innovation",
    },
}

_DEFAULT_ARCHETYPE = {
    "archetype": "The Sage",
    "traits": ["knowledgeable", "trustworthy", "analytical", "wise"],
    "tone_keywords": ["informed", "clear", "credible"],
    "emotional_appeal": "trust and expertise",
}


def profile_personality(
    business: dict[str, Any],
    products: list[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Profile brand personality based on business context.

    Args:
        business: Business info dict with name, category, target_audience.
        products: List of product dicts.
        competitors: List of competitor dicts.

    Returns:
        Structured dict with personality profile.
    """
    try:
        biz = copy.deepcopy(business)
        category = str(biz.get("category", "")).lower()
        audience = str(biz.get("target_audience", "")).lower()

        # Match archetype from category keywords
        matched = None
        for keyword, archetype_data in _ARCHETYPE_MAP.items():
            if keyword in category or keyword in audience:
                matched = copy.deepcopy(archetype_data)
                break

        if matched is None:
            matched = copy.deepcopy(_DEFAULT_ARCHETYPE)

        # Enrich traits based on audience keywords
        if "young" in audience or "gen z" in audience or "millennial" in audience:
            matched["traits"].append("trendy")
            matched["tone_keywords"].append("relatable")
        if "professional" in audience or "business" in audience:
            matched["traits"].append("professional")
            matched["tone_keywords"].append("authoritative")
        if "eco" in category or "sustainable" in category:
            matched["traits"].append("eco-conscious")
            matched["tone_keywords"].append("responsible")

        # Deduplicate
        matched["traits"] = list(dict.fromkeys(matched["traits"]))
        matched["tone_keywords"] = list(dict.fromkeys(matched["tone_keywords"]))

        return {
            "status": "success",
            "personality": matched,
        }
    except Exception as exc:
        return {
            "status": "error",
            "personality": {},
            "error": f"Personality profiling failed: {exc}",
        }
