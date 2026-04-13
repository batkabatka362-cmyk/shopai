"""Content Generation Engine — tone selector.

Selects the appropriate tone and voice for generated content based on brand
guidelines, target audience, and content type.

No model dependency — pure rule-based selection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Tone profiles
# ---------------------------------------------------------------------------

_TONE_PROFILES: dict[str, dict[str, Any]] = {
    "professional": {
        "formality_level": 0.8,
        "emotional_appeal": "trust",
        "vocabulary_level": "advanced",
        "sentence_style": "structured",
    },
    "casual": {
        "formality_level": 0.3,
        "emotional_appeal": "relatability",
        "vocabulary_level": "conversational",
        "sentence_style": "short_and_punchy",
    },
    "urgent": {
        "formality_level": 0.5,
        "emotional_appeal": "fomo",
        "vocabulary_level": "simple",
        "sentence_style": "short_and_direct",
    },
    "luxury": {
        "formality_level": 0.9,
        "emotional_appeal": "aspiration",
        "vocabulary_level": "sophisticated",
        "sentence_style": "elegant",
    },
    "playful": {
        "formality_level": 0.2,
        "emotional_appeal": "joy",
        "vocabulary_level": "simple",
        "sentence_style": "witty",
    },
    "informative": {
        "formality_level": 0.7,
        "emotional_appeal": "confidence",
        "vocabulary_level": "clear",
        "sentence_style": "explanatory",
    },
}

# Maps content type to preferred tone when brand voice is unspecified
_CONTENT_TYPE_TONE_DEFAULTS: dict[str, str] = {
    "product_description": "informative",
    "ad_copy": "urgent",
    "social_post": "casual",
    "blog": "informative",
    "email": "professional",
}

# Maps audience keywords to tone adjustments
_AUDIENCE_TONE_HINTS: dict[str, str] = {
    "young": "casual",
    "teen": "playful",
    "professional": "professional",
    "luxury": "luxury",
    "premium": "luxury",
    "budget": "urgent",
    "parent": "informative",
    "tech": "informative",
}


def select_tone(
    content_type: str,
    brand: dict[str, Any],
    target_audience: str,
) -> dict[str, Any]:
    """Select the appropriate tone and voice for the content.

    Args:
        content_type: The type of content being generated.
        brand: BrandData dict with name, voice, values.
        target_audience: Description of the target audience.

    Returns:
        Structured dict with ToneSelection data.
    """
    try:
        brnd = copy.deepcopy(brand)
        brand_voice = str(brnd.get("voice", "")).strip().lower()
        audience_lower = target_audience.lower()

        # Determine primary tone: brand voice takes priority
        if brand_voice in _TONE_PROFILES:
            primary_tone = brand_voice
        else:
            primary_tone = _CONTENT_TYPE_TONE_DEFAULTS.get(content_type, "professional")

        # Determine secondary tone from audience hints
        secondary_tone = _resolve_audience_tone(audience_lower, primary_tone)

        profile = _TONE_PROFILES.get(primary_tone, _TONE_PROFILES["professional"])

        return {
            "status": "success",
            "selection": {
                "primary_tone": primary_tone,
                "secondary_tone": secondary_tone,
                "formality_level": profile["formality_level"],
                "emotional_appeal": profile["emotional_appeal"],
                "vocabulary_level": profile["vocabulary_level"],
                "sentence_style": profile["sentence_style"],
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "selection": {},
            "error": f"Tone selection failed: {exc}",
        }


def _resolve_audience_tone(audience: str, fallback: str) -> str:
    """Resolve a secondary tone from audience keywords."""
    for keyword, tone in _AUDIENCE_TONE_HINTS.items():
        if keyword in audience:
            if tone != fallback:
                return tone
    # Default secondary: complement the primary
    complements: dict[str, str] = {
        "professional": "informative",
        "casual": "playful",
        "urgent": "casual",
        "luxury": "professional",
        "playful": "casual",
        "informative": "professional",
    }
    return complements.get(fallback, "professional")
