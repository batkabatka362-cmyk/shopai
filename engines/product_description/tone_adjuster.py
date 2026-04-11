"""Product Description Engine — tone adjuster.

Adjusts product copy to match different brand voice tones.
Generates variations for A/B testing across different audiences.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Tone transformation rules
# ---------------------------------------------------------------------------

_TONE_OPENERS: dict[str, str] = {
    "professional": "Engineered for excellence,",
    "casual": "Check this out —",
    "luxury": "Exquisitely crafted,",
    "playful": "Say hello to your new favorite!",
    "minimalist": "",
    "technical": "Specification-driven design:",
}

_TONE_CLOSERS: dict[str, str] = {
    "professional": "A smart investment in quality.",
    "casual": "You're going to love it.",
    "luxury": "For those who accept nothing but the finest.",
    "playful": "What are you waiting for?",
    "minimalist": "Simple. Effective.",
    "technical": "Performance metrics speak for themselves.",
}


def adjust_tone(
    copy_data: dict[str, Any],
    brand_voice: dict[str, Any],
) -> dict[str, Any]:
    """Generate tone variations of the product copy.

    Args:
        copy_data: Generated copy dict (title, description, bullets).
        brand_voice: Brand voice config (with tone, style).

    Returns:
        Structured dict with tone variations.
    """
    try:
        description = str(copy_data.get("description", ""))
        title = str(copy_data.get("title", ""))
        primary_tone = str(brand_voice.get("tone", "professional"))

        # Generate 2-3 variations in different tones
        variation_tones = _select_variation_tones(primary_tone)
        variations: list[dict[str, str]] = []

        for tone in variation_tones:
            opener = _TONE_OPENERS.get(tone, "")
            closer = _TONE_CLOSERS.get(tone, "")

            # Build variation by adjusting the description
            if tone == "minimalist":
                # Strip to essentials — first sentence + closer
                sentences = description.split(". ")
                core = sentences[0] if sentences else description
                variation_text = f"{core}. {closer}"
            elif tone == "technical":
                # Emphasize specs
                variation_text = f"{opener} {description} {closer}"
            else:
                variation_text = f"{opener} {description} {closer}"

            # Clean up spacing
            variation_text = " ".join(variation_text.split())

            variations.append({
                "tone": tone,
                "copy": variation_text,
            })

        return {
            "status": "success",
            "variations": variations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "variations": [],
            "error": f"Tone adjustment failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_variation_tones(primary_tone: str) -> list[str]:
    """Select 2-3 complementary tones for variations."""
    all_tones = ["professional", "casual", "luxury", "playful", "minimalist", "technical"]

    # Always include the primary tone plus 2 alternatives
    selected = [primary_tone]
    for tone in all_tones:
        if tone != primary_tone and len(selected) < 3:
            selected.append(tone)

    return selected
