"""Brand Identity Engine — story crafter.

Crafts brand origin story, mission statement, vision, and tagline.
Derives narrative from personality, business context, and values.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Story templates by archetype
# ---------------------------------------------------------------------------

_STORY_TEMPLATES: dict[str, dict[str, str]] = {
    "The Ruler": {
        "origin_template": "{name} was founded with a singular vision: to set the standard in {category}. Born from a refusal to accept mediocrity, every decision has been guided by an unwavering commitment to excellence.",
        "mission_template": "To deliver unmatched {category} experiences that empower {audience} to lead with confidence and distinction.",
        "vision_template": "To be the definitive authority in {category}, recognized globally for setting the benchmark of quality and sophistication.",
        "tagline_template": "{name} — The Standard of Excellence",
    },
    "The Magician": {
        "origin_template": "{name} started with a bold question: what if {category} could be reimagined from the ground up? That question sparked a movement to transform how {audience} experience the world.",
        "mission_template": "To harness innovation in {category} that transforms everyday experiences for {audience} into something extraordinary.",
        "vision_template": "To pioneer the future of {category}, making the impossible possible for {audience} everywhere.",
        "tagline_template": "{name} — Transforming What's Possible",
    },
    "The Explorer": {
        "origin_template": "{name} was born on the open road — a brand built for those who refuse to stay still. From day one, the mission has been to equip {audience} for their next great adventure in {category}.",
        "mission_template": "To fuel the spirit of adventure in {audience} through fearless innovation in {category}.",
        "vision_template": "To be the trusted companion for every {audience} who dares to explore, discover, and push boundaries.",
        "tagline_template": "{name} — Never Stop Exploring",
    },
    "The Caregiver": {
        "origin_template": "{name} began with a simple belief: everyone deserves to feel cared for. Built to serve {audience}, every product in {category} is crafted with compassion and purpose.",
        "mission_template": "To protect and nurture the well-being of {audience} through thoughtful, trusted {category} solutions.",
        "vision_template": "To create a world where {audience} feel supported, safe, and empowered to thrive.",
        "tagline_template": "{name} — Because You Matter",
    },
    "The Lover": {
        "origin_template": "{name} was born from a passion for beauty and connection. Every creation in {category} is designed to make {audience} feel confident, seen, and celebrated.",
        "mission_template": "To inspire {audience} to embrace their individuality through captivating {category} experiences.",
        "vision_template": "To be the ultimate expression of style and passion in {category}, cherished by {audience} worldwide.",
        "tagline_template": "{name} — Embrace Your Beauty",
    },
    "The Everyman": {
        "origin_template": "{name} started in a kitchen, a garage, a place just like yours. Built for real people, {name} brings honest, quality {category} to {audience} without the pretense.",
        "mission_template": "To make great {category} accessible and enjoyable for every {audience}, every day.",
        "vision_template": "To be the brand {audience} trust like a good neighbor — always reliable, always real.",
        "tagline_template": "{name} — Made for Real Life",
    },
    "The Hero": {
        "origin_template": "{name} was forged in the pursuit of greatness. Built for {audience} who refuse to settle, every product in {category} is designed to help you push past limits.",
        "mission_template": "To empower {audience} to achieve their greatest potential through world-class {category} performance.",
        "vision_template": "To be the catalyst that transforms ambition into achievement for {audience} everywhere.",
        "tagline_template": "{name} — Rise Above",
    },
    "The Innocent": {
        "origin_template": "{name} was created to bring joy and simplicity back to {category}. For {audience} who believe life should be fun, bright, and full of wonder.",
        "mission_template": "To fill the world of {audience} with happiness through delightful, simple {category} experiences.",
        "vision_template": "To be the brightest, most joyful brand in {category}, bringing smiles to {audience} everywhere.",
        "tagline_template": "{name} — Joy in Every Moment",
    },
    "The Creator": {
        "origin_template": "{name} was born from the belief that {category} is an art form. For {audience} who see the world as a canvas, every product is designed to unleash imagination.",
        "mission_template": "To inspire {audience} to create, express, and innovate through visionary {category} tools and experiences.",
        "vision_template": "To be the creative force behind every {audience} who dares to imagine something original.",
        "tagline_template": "{name} — Create Without Limits",
    },
    "The Sage": {
        "origin_template": "{name} was founded on the principle that knowledge is power. In {category}, informed decisions lead to better outcomes for {audience}.",
        "mission_template": "To empower {audience} with expert knowledge and proven {category} solutions they can trust.",
        "vision_template": "To be the most trusted source of expertise in {category}, guiding {audience} to smarter choices.",
        "tagline_template": "{name} — Knowledge You Can Trust",
    },
}


def craft_story(
    personality: dict[str, Any],
    business: dict[str, Any],
) -> dict[str, Any]:
    """Craft brand origin story, mission, vision, and tagline.

    Args:
        personality: Brand personality dict with archetype.
        business: Business info dict with name, category, target_audience.

    Returns:
        Structured dict with brand story.
    """
    try:
        biz = copy.deepcopy(business)
        archetype = str(personality.get("archetype", "The Sage"))
        name = str(biz.get("name", "Our Brand"))
        category = str(biz.get("category", "our industry"))
        audience = str(biz.get("target_audience", "our customers"))

        templates = _STORY_TEMPLATES.get(archetype, _STORY_TEMPLATES["The Sage"])

        story = {
            "origin": templates["origin_template"].format(
                name=name, category=category, audience=audience,
            ),
            "mission": templates["mission_template"].format(
                name=name, category=category, audience=audience,
            ),
            "vision": templates["vision_template"].format(
                name=name, category=category, audience=audience,
            ),
            "tagline": templates["tagline_template"].format(
                name=name, category=category, audience=audience,
            ),
        }

        return {
            "status": "success",
            "story": story,
        }
    except Exception as exc:
        return {
            "status": "error",
            "story": {},
            "error": f"Story crafting failed: {exc}",
        }
