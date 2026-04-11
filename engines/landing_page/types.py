"""Landing Page Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the landing page engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInput(TypedDict, total=False):
    """Product data for landing page generation."""
    id: str
    title: str
    description: str
    price: float
    features: list[str]
    images: list[str]
    category: str


class CampaignInput(TypedDict, total=False):
    """Campaign context."""
    name: str
    goal: str
    channel: str
    budget: float
    start_date: str
    end_date: str


class LandingPageInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: ProductInput
    campaign: CampaignInput
    target_audience: str
    brand_voice: str


# ---------------------------------------------------------------------------
# Intermediate types — page generation
# ---------------------------------------------------------------------------

class PageStructure(TypedDict):
    """Generated page structure."""
    headline: str
    subheadline: str
    hero_section: str
    benefits: list[str]
    cta: str
    social_proof: str
    layout: str


# ---------------------------------------------------------------------------
# Intermediate types — headline optimization
# ---------------------------------------------------------------------------

class HeadlineVariant(TypedDict):
    """A headline variant for A/B testing."""
    text: str
    framework: str
    estimated_ctr: float
    emotional_appeal: str


# ---------------------------------------------------------------------------
# Intermediate types — CTA optimization
# ---------------------------------------------------------------------------

class CTAVariant(TypedDict):
    """A CTA variant."""
    text: str
    style: str
    urgency_level: str
    estimated_click_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — performance scoring
# ---------------------------------------------------------------------------

class PerformanceScore(TypedDict):
    """Page performance score breakdown."""
    overall: float
    headline_score: float
    cta_score: float
    social_proof_score: float
    mobile_readiness: float
    load_speed_estimate: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class PageResult(TypedDict):
    """Single page variant in the output."""
    headline: str
    subheadline: str
    hero_section: str
    benefits: list[str]
    cta: str
    social_proof: str


class LandingPageData(TypedDict):
    """The 'data' block of engine output."""
    pages: list[PageResult]
    best_variant: int
    estimated_conversion: float


class LandingPageMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class LandingPageOutput(TypedDict):
    """Final output of the landing page engine."""
    status: str
    data: LandingPageData | None
    meta: LandingPageMeta
    error: str | None
