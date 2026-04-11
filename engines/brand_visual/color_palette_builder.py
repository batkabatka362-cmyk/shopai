"""Brand Visual Engine — color palette builder.

Builds primary, secondary, accent, background, and text colors
from industry, personality archetype, and preferences.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Color palettes by archetype
# ---------------------------------------------------------------------------

_PALETTE_MAP: dict[str, dict[str, str]] = {
    "The Ruler": {
        "primary": "#1B1B2F",
        "secondary": "#162447",
        "accent": "#C6A962",
        "background": "#F5F3EE",
        "text": "#1B1B2F",
        "palette_name": "Royal Authority",
    },
    "The Magician": {
        "primary": "#6C63FF",
        "secondary": "#3F3D56",
        "accent": "#FF6584",
        "background": "#F8F9FA",
        "text": "#2D2D2D",
        "palette_name": "Digital Enchantment",
    },
    "The Explorer": {
        "primary": "#2D6A4F",
        "secondary": "#40916C",
        "accent": "#D4A373",
        "background": "#FEFAE0",
        "text": "#2D3436",
        "palette_name": "Wilderness Trail",
    },
    "The Caregiver": {
        "primary": "#4A90D9",
        "secondary": "#7EC8E3",
        "accent": "#F8B400",
        "background": "#F0F7FF",
        "text": "#2C3E50",
        "palette_name": "Gentle Trust",
    },
    "The Lover": {
        "primary": "#C2185B",
        "secondary": "#880E4F",
        "accent": "#FF6F91",
        "background": "#FFF0F3",
        "text": "#3E2723",
        "palette_name": "Passionate Rose",
    },
    "The Everyman": {
        "primary": "#3B7DD8",
        "secondary": "#5B9BD5",
        "accent": "#F4A261",
        "background": "#FFFFFF",
        "text": "#333333",
        "palette_name": "Friendly Blue",
    },
    "The Hero": {
        "primary": "#D32F2F",
        "secondary": "#1565C0",
        "accent": "#FFC107",
        "background": "#FAFAFA",
        "text": "#212121",
        "palette_name": "Bold Champion",
    },
    "The Innocent": {
        "primary": "#FF9A8B",
        "secondary": "#88D8B0",
        "accent": "#FFEAA7",
        "background": "#FFFDF7",
        "text": "#4A4A4A",
        "palette_name": "Joyful Pastels",
    },
    "The Creator": {
        "primary": "#FF6B35",
        "secondary": "#004E89",
        "accent": "#F7C948",
        "background": "#FAFAFA",
        "text": "#1A1A2E",
        "palette_name": "Creative Spark",
    },
    "The Sage": {
        "primary": "#2C3E50",
        "secondary": "#34495E",
        "accent": "#27AE60",
        "background": "#F7F9FC",
        "text": "#2C3E50",
        "palette_name": "Wise Clarity",
    },
}

# Industry-specific overrides for accent colors
_INDUSTRY_ACCENTS: dict[str, str] = {
    "health": "#2ECC71",
    "finance": "#2980B9",
    "food": "#E67E22",
    "eco": "#27AE60",
    "luxury": "#C6A962",
    "tech": "#6C63FF",
}


def build_color_palette(
    brand_identity: dict[str, Any],
    industry: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Build a color palette from brand identity and industry context.

    Args:
        brand_identity: Brand identity data with personality archetype.
        industry: Industry string.
        preferences: User color preferences (optional overrides).

    Returns:
        Structured dict with color palette.
    """
    try:
        personality = brand_identity.get("personality", {})
        archetype = str(personality.get("archetype", "The Sage"))

        palette = copy.deepcopy(_PALETTE_MAP.get(archetype, _PALETTE_MAP["The Sage"]))

        # Apply industry accent override if relevant
        industry_lower = industry.lower()
        for keyword, accent in _INDUSTRY_ACCENTS.items():
            if keyword in industry_lower:
                palette["accent"] = accent
                break

        # Apply user preference overrides
        prefs = preferences or {}
        for key in ("primary", "secondary", "accent", "background", "text"):
            if prefs.get(key):
                palette[key] = str(prefs[key])

        return {
            "status": "success",
            "colors": palette,
        }
    except Exception as exc:
        return {
            "status": "error",
            "colors": {},
            "error": f"Color palette building failed: {exc}",
        }
