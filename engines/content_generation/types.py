"""Content Generation Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the content generation engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductData(TypedDict, total=False):
    """Product information for content generation."""
    title: str
    features: list[str]
    price: float
    category: str
    target_audience: str


class BrandData(TypedDict, total=False):
    """Brand context for content generation."""
    name: str
    voice: str
    values: list[str]


class ContentRequestData(TypedDict, total=False):
    """Top-level data block from the engine input."""
    type: str
    product: ProductData
    brand: BrandData
    platform: str


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class BriefAnalysis(TypedDict):
    """Analysis result from brief_analyzer."""
    content_type: str
    product_features: list[str]
    usps: list[str]
    target_audience: str
    audience_pain_points: list[str]
    desired_outcome: str
    model_note: str


class ToneSelection(TypedDict):
    """Tone/voice selection from tone_selector."""
    primary_tone: str
    secondary_tone: str
    formality_level: float
    emotional_appeal: str
    vocabulary_level: str
    sentence_style: str


class KeywordExtraction(TypedDict):
    """Keyword extraction result from keyword_extractor."""
    primary_keywords: list[str]
    secondary_keywords: list[str]
    long_tail_keywords: list[str]
    related_terms: list[str]
    target_density: float


class CopyDraft(TypedDict):
    """Copy draft from copy_writer."""
    headline: str
    body: str
    bullets: list[str]
    cta: str
    alt_headlines: list[str]
    model_note: str


class SEOResult(TypedDict):
    """SEO optimization result from seo_optimizer."""
    meta_description: str
    title_tag: str
    alt_text_suggestions: list[str]
    keyword_density: dict[str, float]
    seo_score: float
    recommendations: list[str]


class FormatResult(TypedDict):
    """Format adaptation result from format_adapter."""
    formatted_content: dict[str, str]
    platform: str
    character_count: int
    within_limits: bool
    model_note: str


class QualityResult(TypedDict):
    """Quality check result from quality_checker."""
    readability_score: float
    flesch_kincaid_grade: float
    grammar_flags: list[str]
    brand_voice_consistent: bool
    keyword_presence: dict[str, bool]
    overall_quality: float
    model_note: str


class ContentVariation(TypedDict):
    """Single content variation for A/B testing."""
    variant_id: str
    headline: str
    body: str
    cta: str
    variation_focus: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ContentGenerationOutput(TypedDict):
    """Final output of the content generation engine."""
    status: str
    data: ContentGenerationData | None
    meta: ContentGenerationMeta
    error: str | None


class ContentGenerationData(TypedDict):
    """The 'data' block of the engine output."""
    content: ContentBlock
    seo_score: float
    readability_score: float
    variations: list[ContentVariation]
    confidence: float


class ContentBlock(TypedDict):
    """The generated content block."""
    headline: str
    body: str
    bullets: list[str]
    cta: str
    meta_description: str


class ContentGenerationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
