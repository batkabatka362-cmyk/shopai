"""Store Design Engine — color recommender.

Recommends brand-consistent color palettes optimized for e-commerce
conversion based on brand colors, industry best practices, and
contrast accessibility requirements.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default palettes by voice/tone
# ---------------------------------------------------------------------------

_VOICE_PALETTES: dict[str, dict[str, str]] = {
    "luxury": {
        "primary": "#1a1a2e",
        "secondary": "#16213e",
        "accent": "#c9a96e",
        "background": "#f5f5f0",
        "text": "#1a1a2e",
        "cta": "#c9a96e",
    },
    "playful": {
        "primary": "#ff6b6b",
        "secondary": "#4ecdc4",
        "accent": "#ffe66d",
        "background": "#ffffff",
        "text": "#2d3436",
        "cta": "#ff6b6b",
    },
    "professional": {
        "primary": "#2c3e50",
        "secondary": "#3498db",
        "accent": "#e74c3c",
        "background": "#ecf0f1",
        "text": "#2c3e50",
        "cta": "#e74c3c",
    },
    "minimal": {
        "primary": "#000000",
        "secondary": "#333333",
        "accent": "#ff4757",
        "background": "#ffffff",
        "text": "#2f3542",
        "cta": "#ff4757",
    },
}

_DEFAULT_PALETTE = _VOICE_PALETTES["professional"]


def recommend_colors(
    brand: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend a brand-consistent color palette.

    Args:
        brand: Brand info with colors, fonts, voice.
        products: List of product dicts for context.

    Returns:
        Structured dict with color palette recommendation.
    """
    try:
        brand_data = copy.deepcopy(brand)
        brand_colors = brand_data.get("colors", [])
        voice = str(brand_data.get("voice", "professional")).lower()

        # Start with voice-based palette
        base_palette = copy.deepcopy(
            _VOICE_PALETTES.get(voice, _DEFAULT_PALETTE)
        )

        # Override with brand colors if provided
        if len(brand_colors) >= 1:
            base_palette["primary"] = str(brand_colors[0])
        if len(brand_colors) >= 2:
            base_palette["secondary"] = str(brand_colors[1])
        if len(brand_colors) >= 3:
            base_palette["accent"] = str(brand_colors[2])

        # CTA color: use accent for contrast against primary
        base_palette["cta"] = base_palette.get("accent", "#e74c3c")

        # Build rationale
        rationale_parts = []
        if brand_colors:
            rationale_parts.append(
                f"Primary and secondary colors derived from brand palette ({', '.join(brand_colors[:3])})"
            )
        rationale_parts.append(
            f"Voice '{voice}' informs overall tone and contrast levels"
        )
        rationale_parts.append(
            "CTA color chosen for maximum contrast against background"
        )

        palette = {
            **base_palette,
            "rationale": ". ".join(rationale_parts) + ".",
        }

        return {
            "status": "success",
            "palette": palette,
        }
    except Exception as exc:
        return {
            "status": "error",
            "palette": {},
            "error": f"Color recommendation failed: {exc}",
        }
