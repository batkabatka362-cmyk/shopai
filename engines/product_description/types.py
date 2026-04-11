"""Product Description Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product description engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInfo(TypedDict, total=False):
    """Product data for description generation."""
    id: str
    title: str
    category: str
    features: list[str]
    specifications: dict[str, str]
    price: float
    images: list[str]


class BrandVoice(TypedDict, total=False):
    """Brand voice configuration."""
    tone: str
    style: str
    audience: str
    brand_name: str
    values: list[str]


class CompetitorInfo(TypedDict, total=False):
    """Competitor product data for differentiation."""
    title: str
    description: str
    price: float
    keywords: list[str]


class ProductDescInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: ProductInfo
    brand_voice: BrandVoice
    target_keywords: list[str]
    competitors: list[CompetitorInfo]


# ---------------------------------------------------------------------------
# Intermediate types — feature extraction
# ---------------------------------------------------------------------------

class ExtractedFeature(TypedDict):
    """Extracted feature from feature_extractor."""
    feature: str
    benefit: str
    priority: int
    category: str


# ---------------------------------------------------------------------------
# Intermediate types — copy writing
# ---------------------------------------------------------------------------

class GeneratedCopy(TypedDict):
    """Generated copy from copy_writer."""
    title: str
    subtitle: str
    bullet_points: list[str]
    description: str


# ---------------------------------------------------------------------------
# Intermediate types — SEO optimization
# ---------------------------------------------------------------------------

class SEOResult(TypedDict):
    """SEO optimization result from seo_optimizer."""
    meta_title: str
    meta_description: str
    seo_score: float
    keyword_density: dict[str, float]
    suggestions: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — tone adjustment
# ---------------------------------------------------------------------------

class ToneVariation(TypedDict):
    """Tone-adjusted copy variation from tone_adjuster."""
    tone: str
    copy: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProductDescOutputData(TypedDict):
    """The 'data' block of the engine output."""
    title: str
    subtitle: str
    bullet_points: list[str]
    description: str
    meta_title: str
    meta_description: str
    seo_score: float
    variations: list[ToneVariation]


class ProductDescMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ProductDescOutput(TypedDict):
    """Final output of the product description engine."""
    status: str
    data: ProductDescOutputData | None
    meta: ProductDescMeta
    error: str | None
