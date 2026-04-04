"""Brand Visual Engine — typography selector.

Recommends font pairings for headings and body text based on
brand personality and industry context.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Font pairings by archetype
# ---------------------------------------------------------------------------

_FONT_MAP: dict[str, dict[str, Any]] = {
    "The Ruler": {
        "heading_font": "Playfair Display",
        "body_font": "Lato",
        "sizes": {"h1": "48px", "h2": "36px", "h3": "28px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "600"},
    },
    "The Magician": {
        "heading_font": "Space Grotesk",
        "body_font": "Inter",
        "sizes": {"h1": "44px", "h2": "32px", "h3": "24px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "500"},
    },
    "The Explorer": {
        "heading_font": "Oswald",
        "body_font": "Source Sans Pro",
        "sizes": {"h1": "46px", "h2": "34px", "h3": "26px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "600", "body": "400", "emphasis": "600"},
    },
    "The Caregiver": {
        "heading_font": "Nunito",
        "body_font": "Open Sans",
        "sizes": {"h1": "42px", "h2": "32px", "h3": "24px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "600"},
    },
    "The Lover": {
        "heading_font": "Cormorant Garamond",
        "body_font": "Raleway",
        "sizes": {"h1": "46px", "h2": "34px", "h3": "26px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "600", "body": "400", "emphasis": "500"},
    },
    "The Everyman": {
        "heading_font": "Roboto",
        "body_font": "Roboto",
        "sizes": {"h1": "40px", "h2": "30px", "h3": "22px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "500"},
    },
    "The Hero": {
        "heading_font": "Montserrat",
        "body_font": "Hind",
        "sizes": {"h1": "48px", "h2": "36px", "h3": "28px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "800", "body": "400", "emphasis": "600"},
    },
    "The Innocent": {
        "heading_font": "Quicksand",
        "body_font": "Poppins",
        "sizes": {"h1": "42px", "h2": "32px", "h3": "24px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "500"},
    },
    "The Creator": {
        "heading_font": "DM Sans",
        "body_font": "Work Sans",
        "sizes": {"h1": "44px", "h2": "34px", "h3": "26px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "500"},
    },
    "The Sage": {
        "heading_font": "Merriweather",
        "body_font": "Source Sans Pro",
        "sizes": {"h1": "42px", "h2": "32px", "h3": "24px", "body": "16px", "small": "14px"},
        "weight_guidelines": {"heading": "700", "body": "400", "emphasis": "600"},
    },
}


def select_typography(
    brand_identity: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Select typography based on brand identity.

    Args:
        brand_identity: Brand identity data with personality archetype.
        preferences: User typography preferences (optional overrides).

    Returns:
        Structured dict with typography recommendations.
    """
    try:
        personality = brand_identity.get("personality", {})
        archetype = str(personality.get("archetype", "The Sage"))

        typography = copy.deepcopy(_FONT_MAP.get(archetype, _FONT_MAP["The Sage"]))

        # Apply user preference overrides
        prefs = preferences or {}
        if prefs.get("heading_font"):
            typography["heading_font"] = str(prefs["heading_font"])
        if prefs.get("body_font"):
            typography["body_font"] = str(prefs["body_font"])

        return {
            "status": "success",
            "typography": typography,
        }
    except Exception as exc:
        return {
            "status": "error",
            "typography": {},
            "error": f"Typography selection failed: {exc}",
        }
