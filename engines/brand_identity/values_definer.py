"""Brand Identity Engine — values definer.

Defines core brand values, positioning statement, and value propositions.
Derives from personality, business context, and competitive landscape.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Values by archetype
# ---------------------------------------------------------------------------

_VALUES_MAP: dict[str, list[str]] = {
    "The Ruler": ["Excellence", "Authority", "Quality", "Prestige", "Leadership"],
    "The Magician": ["Innovation", "Transformation", "Vision", "Impact", "Progress"],
    "The Explorer": ["Freedom", "Adventure", "Authenticity", "Courage", "Discovery"],
    "The Caregiver": ["Compassion", "Trust", "Safety", "Nurturing", "Integrity"],
    "The Lover": ["Passion", "Beauty", "Connection", "Intimacy", "Expression"],
    "The Everyman": ["Honesty", "Accessibility", "Community", "Reliability", "Simplicity"],
    "The Hero": ["Courage", "Determination", "Excellence", "Empowerment", "Achievement"],
    "The Innocent": ["Joy", "Simplicity", "Optimism", "Purity", "Wonder"],
    "The Creator": ["Creativity", "Originality", "Vision", "Expression", "Innovation"],
    "The Sage": ["Knowledge", "Truth", "Expertise", "Wisdom", "Integrity"],
}


def define_values(
    personality: dict[str, Any],
    business: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Define core brand values and positioning statement.

    Args:
        personality: Brand personality dict with archetype and traits.
        business: Business info dict.
        competitors: List of competitor dicts.

    Returns:
        Structured dict with values and positioning statement.
    """
    try:
        biz = copy.deepcopy(business)
        archetype = str(personality.get("archetype", "The Sage"))
        name = str(biz.get("name", "Our Brand"))
        category = str(biz.get("category", "our industry"))
        audience = str(biz.get("target_audience", "our customers"))

        values = _VALUES_MAP.get(archetype, _VALUES_MAP["The Sage"])

        # Add eco-conscious value if category suggests it
        cat_lower = category.lower()
        if any(kw in cat_lower for kw in ("eco", "sustainable", "green", "organic")):
            if "Sustainability" not in values:
                values = values[:4] + ["Sustainability"]

        # Build positioning statement
        competitor_names = [str(c.get("name", "")) for c in competitors if c.get("name")]
        differentiator = personality.get("traits", ["unique"])[0]

        if competitor_names:
            comp_clause = f"Unlike {competitor_names[0]}, "
        else:
            comp_clause = "In a crowded market, "

        positioning_statement = (
            f"For {audience} who demand the best in {category}, "
            f"{name} is the {differentiator} choice that delivers "
            f"unmatched value. {comp_clause}{name} stands apart through "
            f"an unwavering commitment to {values[0].lower()} and {values[1].lower()}."
        )

        # Value propositions
        value_propositions = [
            f"Committed to {values[0].lower()} in every aspect of {category}",
            f"Built by and for {audience} who value {values[1].lower()}",
            f"Driven by {values[2].lower()} to continuously improve your experience",
        ]

        return {
            "status": "success",
            "values_result": {
                "values": values,
                "positioning_statement": positioning_statement,
                "value_propositions": value_propositions,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "values_result": {},
            "error": f"Values definition failed: {exc}",
        }
