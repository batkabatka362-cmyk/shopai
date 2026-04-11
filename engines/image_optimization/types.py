"""Image Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the image optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ImageInfo(TypedDict, total=False):
    """Single image record."""
    url: str
    alt: str
    size_bytes: int
    width: int
    height: int
    format: str


class ProductInfo(TypedDict, total=False):
    """Product associated with images."""
    id: str
    title: str
    category: str
    features: list[str]


class ImageOptInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    images: list[ImageInfo]
    product: ProductInfo
    platform: str


# ---------------------------------------------------------------------------
# Intermediate types — quality analysis
# ---------------------------------------------------------------------------

class QualityAnalysis(TypedDict):
    """Per-image quality analysis from quality_analyzer."""
    image_id: int
    url: str
    quality_rating: str
    resolution_adequate: bool
    estimated_load_ms: float
    issues: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — alt text
# ---------------------------------------------------------------------------

class AltTextResult(TypedDict):
    """Generated alt text from alt_text_generator."""
    image_id: int
    alt_text: str
    seo_optimized: bool


# ---------------------------------------------------------------------------
# Intermediate types — size optimization
# ---------------------------------------------------------------------------

class SizeRecommendation(TypedDict):
    """Size optimization recommendation from size_optimizer."""
    image_id: int
    current_size_bytes: int
    recommended_size_bytes: int
    compression: str
    recommended_dimensions: str
    savings_pct: float


# ---------------------------------------------------------------------------
# Intermediate types — gallery planning
# ---------------------------------------------------------------------------

class GallerySlot(TypedDict):
    """Gallery position assignment from gallery_planner."""
    position: int
    image_id: int
    image_type: str
    reason: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ImageOptimization(TypedDict):
    """Single image optimization in engine output."""
    image_id: int
    recommended_size: int
    alt_text: str
    compression: str
    priority: int


class ImageOptOutputData(TypedDict):
    """The 'data' block of the engine output."""
    optimizations: list[ImageOptimization]
    gallery_order: list[GallerySlot]
    missing_types: list[str]
    quality_scores: dict[str, Any]


class ImageOptMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ImageOptOutput(TypedDict):
    """Final output of the image optimization engine."""
    status: str
    data: ImageOptOutputData | None
    meta: ImageOptMeta
    error: str | None
