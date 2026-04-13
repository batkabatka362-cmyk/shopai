"""Brand Identity Engine — voice builder.

Builds brand voice guidelines: tone, vocabulary, dos and don'ts.
Derives voice from the personality profile and business context.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Voice templates by archetype
# ---------------------------------------------------------------------------

_VOICE_TEMPLATES: dict[str, dict[str, Any]] = {
    "The Ruler": {
        "tone": "authoritative and refined",
        "vocabulary": ["premium", "exclusive", "curated", "distinguished", "exceptional", "mastercraft"],
        "dos": [
            "Use sophisticated language that conveys authority",
            "Maintain a confident, assured tone",
            "Reference quality and craftsmanship",
            "Address the customer as a discerning individual",
        ],
        "donts": [
            "Use slang or overly casual language",
            "Use excessive exclamation marks",
            "Sound desperate or salesy",
            "Use discount-focused messaging",
        ],
    },
    "The Magician": {
        "tone": "visionary and inspiring",
        "vocabulary": ["transform", "innovate", "seamless", "intelligent", "breakthrough", "next-gen"],
        "dos": [
            "Focus on transformation and possibility",
            "Use forward-looking language",
            "Highlight how technology improves lives",
            "Be clear and jargon-free when possible",
        ],
        "donts": [
            "Use overly technical jargon without context",
            "Sound robotic or impersonal",
            "Make vague or unsubstantiated claims",
            "Ignore the human element",
        ],
    },
    "The Explorer": {
        "tone": "adventurous and authentic",
        "vocabulary": ["discover", "adventure", "journey", "unleash", "trailblaze", "explore"],
        "dos": [
            "Evoke a sense of adventure and possibility",
            "Use active, energetic language",
            "Tell stories of exploration and discovery",
            "Be authentic and unpretentious",
        ],
        "donts": [
            "Sound corporate or stuffy",
            "Use passive voice excessively",
            "Be overly cautious in tone",
            "Lose the sense of excitement",
        ],
    },
    "The Caregiver": {
        "tone": "warm and reassuring",
        "vocabulary": ["nurture", "protect", "support", "trust", "gentle", "wellness"],
        "dos": [
            "Use empathetic, caring language",
            "Reassure and build trust",
            "Focus on benefits to well-being",
            "Be inclusive and supportive",
        ],
        "donts": [
            "Use fear-based marketing",
            "Sound condescending or preachy",
            "Make exaggerated health claims",
            "Be impersonal or cold",
        ],
    },
    "The Lover": {
        "tone": "passionate and expressive",
        "vocabulary": ["allure", "desire", "indulge", "captivate", "radiant", "embrace"],
        "dos": [
            "Appeal to the senses and emotions",
            "Use rich, descriptive language",
            "Create a sense of intimacy and connection",
            "Celebrate individuality and self-expression",
        ],
        "donts": [
            "Be bland or generic",
            "Use overly clinical language",
            "Ignore the emotional context",
            "Be objectifying or insensitive",
        ],
    },
    "The Everyman": {
        "tone": "friendly and genuine",
        "vocabulary": ["real", "honest", "together", "enjoy", "simple", "everyday"],
        "dos": [
            "Use conversational, approachable language",
            "Be relatable and down-to-earth",
            "Focus on shared experiences",
            "Keep messaging simple and clear",
        ],
        "donts": [
            "Sound elitist or exclusive",
            "Use complicated jargon",
            "Be inauthentic or try too hard",
            "Alienate any group of people",
        ],
    },
    "The Hero": {
        "tone": "motivating and bold",
        "vocabulary": ["achieve", "conquer", "strength", "push", "unstoppable", "champion"],
        "dos": [
            "Inspire action and determination",
            "Use powerful, action-oriented language",
            "Celebrate achievements and milestones",
            "Empower the customer as the hero",
        ],
        "donts": [
            "Sound aggressive or intimidating",
            "Shame or belittle the audience",
            "Make unrealistic promises",
            "Ignore the journey — only focus on results",
        ],
    },
    "The Innocent": {
        "tone": "cheerful and optimistic",
        "vocabulary": ["joy", "wonder", "delight", "bright", "play", "happy"],
        "dos": [
            "Keep language positive and uplifting",
            "Use simple, clear words",
            "Evoke a sense of wonder and fun",
            "Be inclusive and family-friendly",
        ],
        "donts": [
            "Use negative or fear-based language",
            "Be cynical or sarcastic",
            "Use complex or adult-oriented messaging",
            "Overwhelm with too much information",
        ],
    },
    "The Creator": {
        "tone": "imaginative and inspiring",
        "vocabulary": ["create", "design", "imagine", "craft", "original", "vision"],
        "dos": [
            "Celebrate creativity and originality",
            "Use vivid, descriptive language",
            "Encourage experimentation and expression",
            "Showcase the creative process",
        ],
        "donts": [
            "Be formulaic or generic",
            "Stifle individuality",
            "Use overly corporate language",
            "Ignore the artistic perspective",
        ],
    },
    "The Sage": {
        "tone": "informed and thoughtful",
        "vocabulary": ["insight", "knowledge", "discover", "understand", "proven", "expert"],
        "dos": [
            "Back claims with evidence and data",
            "Use precise, clear language",
            "Educate and inform the audience",
            "Maintain a calm, authoritative tone",
        ],
        "donts": [
            "Oversimplify complex topics",
            "Sound arrogant or dismissive",
            "Use hype or exaggeration",
            "Ignore the audience's intelligence",
        ],
    },
}


def build_voice(
    personality: dict[str, Any],
    business: dict[str, Any],
) -> dict[str, Any]:
    """Build brand voice guidelines from personality profile.

    Args:
        personality: Brand personality dict with archetype and traits.
        business: Business info dict.

    Returns:
        Structured dict with voice guidelines.
    """
    try:
        archetype = str(personality.get("archetype", "The Sage"))
        template = copy.deepcopy(_VOICE_TEMPLATES.get(archetype, _VOICE_TEMPLATES["The Sage"]))

        # Enrich vocabulary with personality tone keywords
        tone_keywords = personality.get("tone_keywords", [])
        for kw in tone_keywords:
            if kw not in template["vocabulary"]:
                template["vocabulary"].append(kw)

        return {
            "status": "success",
            "voice": template,
        }
    except Exception as exc:
        return {
            "status": "error",
            "voice": {},
            "error": f"Voice building failed: {exc}",
        }
