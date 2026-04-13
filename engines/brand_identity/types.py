"""Brand Identity Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the brand identity engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BusinessInfo(TypedDict, total=False):
    """Business information for brand identity generation."""
    name: str
    category: str
    target_audience: str


class BrandIdentityInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    business: BusinessInfo
    products: list[dict[str, Any]]
    competitors: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — personality
# ---------------------------------------------------------------------------

class BrandPersonality(TypedDict):
    """Brand personality profile from personality_profiler."""
    archetype: str
    traits: list[str]
    tone_keywords: list[str]
    emotional_appeal: str


# ---------------------------------------------------------------------------
# Intermediate types — voice
# ---------------------------------------------------------------------------

class BrandVoice(TypedDict):
    """Brand voice guidelines from voice_builder."""
    tone: str
    vocabulary: list[str]
    dos: list[str]
    donts: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — story
# ---------------------------------------------------------------------------

class BrandStory(TypedDict):
    """Brand story from story_crafter."""
    origin: str
    mission: str
    vision: str
    tagline: str


# ---------------------------------------------------------------------------
# Intermediate types — values
# ---------------------------------------------------------------------------

class BrandValues(TypedDict):
    """Brand values from values_definer."""
    values: list[str]
    positioning_statement: str
    value_propositions: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BrandIdentityData(TypedDict):
    """The 'data' block of the engine output."""
    personality: BrandPersonality
    voice: BrandVoice
    story: BrandStory
    values: list[str]
    positioning_statement: str


class BrandIdentityMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BrandIdentityOutput(TypedDict):
    """Final output of the brand identity engine."""
    status: str
    data: BrandIdentityData | None
    meta: BrandIdentityMeta
    error: str | None
