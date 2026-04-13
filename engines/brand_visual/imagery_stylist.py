"""Brand Visual Engine — imagery stylist.

Defines photography style, mood, composition rules, and color treatment
based on brand personality and industry context.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Imagery styles by archetype
# ---------------------------------------------------------------------------

_IMAGERY_MAP: dict[str, dict[str, Any]] = {
    "The Ruler": {
        "style": "editorial luxury",
        "mood": "sophisticated and aspirational",
        "composition_rules": [
            "Use clean, minimal compositions with ample negative space",
            "Center subjects with symmetrical framing",
            "Prefer studio lighting with rich contrast",
            "Avoid cluttered backgrounds",
        ],
        "color_treatment": "rich, muted tones with high contrast",
    },
    "The Magician": {
        "style": "futuristic and dynamic",
        "mood": "innovative and forward-looking",
        "composition_rules": [
            "Use dynamic angles and perspective",
            "Incorporate light trails and gradients",
            "Show products in context of transformation",
            "Use depth of field to create focus",
        ],
        "color_treatment": "vibrant gradients with tech-inspired hues",
    },
    "The Explorer": {
        "style": "documentary and natural",
        "mood": "adventurous and authentic",
        "composition_rules": [
            "Use wide-angle landscape compositions",
            "Capture candid, in-action moments",
            "Emphasize natural lighting and environments",
            "Show products in outdoor, real-world settings",
        ],
        "color_treatment": "warm, natural earth tones with golden hour warmth",
    },
    "The Caregiver": {
        "style": "warm lifestyle",
        "mood": "gentle and reassuring",
        "composition_rules": [
            "Use soft, natural lighting",
            "Show people connecting and caring",
            "Keep compositions warm and inviting",
            "Avoid harsh shadows or dramatic contrast",
        ],
        "color_treatment": "soft, warm pastels with gentle saturation",
    },
    "The Lover": {
        "style": "sensual and artistic",
        "mood": "passionate and intimate",
        "composition_rules": [
            "Use close-up, detail-oriented shots",
            "Employ dramatic lighting and shadows",
            "Focus on texture and tactile details",
            "Create a sense of intimacy and closeness",
        ],
        "color_treatment": "deep, saturated warm tones with romantic lighting",
    },
    "The Everyman": {
        "style": "casual lifestyle",
        "mood": "friendly and relatable",
        "composition_rules": [
            "Use natural, unposed photography",
            "Show diverse, real people in everyday settings",
            "Keep compositions straightforward and clear",
            "Avoid overly stylized or artificial looks",
        ],
        "color_treatment": "bright, natural colors with balanced exposure",
    },
    "The Hero": {
        "style": "action and performance",
        "mood": "powerful and motivating",
        "composition_rules": [
            "Use low-angle shots for empowerment",
            "Capture peak action and movement",
            "Employ high contrast and bold lighting",
            "Show strength, determination, and achievement",
        ],
        "color_treatment": "high contrast with bold, saturated primary colors",
    },
    "The Innocent": {
        "style": "bright and playful",
        "mood": "joyful and whimsical",
        "composition_rules": [
            "Use bright, even lighting with minimal shadows",
            "Incorporate playful props and colorful elements",
            "Keep compositions simple and uncluttered",
            "Show genuine smiles and joyful moments",
        ],
        "color_treatment": "light, airy pastels with high brightness",
    },
    "The Creator": {
        "style": "artistic and curated",
        "mood": "creative and expressive",
        "composition_rules": [
            "Use unconventional angles and framing",
            "Showcase the creative process and behind-the-scenes",
            "Employ bold color blocking and graphic elements",
            "Allow for visual experimentation and asymmetry",
        ],
        "color_treatment": "bold, contrasting colors with artistic flair",
    },
    "The Sage": {
        "style": "clean and informative",
        "mood": "professional and credible",
        "composition_rules": [
            "Use clean, well-lit product photography",
            "Maintain consistent framing and spacing",
            "Prefer structured, grid-based layouts",
            "Show detail and craftsmanship clearly",
        ],
        "color_treatment": "neutral, professional tones with clear white balance",
    },
}


def define_imagery_style(
    brand_identity: dict[str, Any],
    industry: str,
) -> dict[str, Any]:
    """Define imagery style based on brand identity.

    Args:
        brand_identity: Brand identity data with personality archetype.
        industry: Industry string.

    Returns:
        Structured dict with imagery style guidelines.
    """
    try:
        personality = brand_identity.get("personality", {})
        archetype = str(personality.get("archetype", "The Sage"))

        imagery = copy.deepcopy(_IMAGERY_MAP.get(archetype, _IMAGERY_MAP["The Sage"]))

        # Add industry-specific composition rule
        industry_lower = industry.lower()
        if "food" in industry_lower:
            imagery["composition_rules"].append("Use overhead flat-lay and close-up food styling")
        elif "fashion" in industry_lower:
            imagery["composition_rules"].append("Include lookbook-style editorial compositions")
        elif "tech" in industry_lower:
            imagery["composition_rules"].append("Show clean product renders on minimal backgrounds")

        return {
            "status": "success",
            "imagery": imagery,
        }
    except Exception as exc:
        return {
            "status": "error",
            "imagery": {},
            "error": f"Imagery styling failed: {exc}",
        }
