"""Video Marketing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the video marketing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInfo(TypedDict, total=False):
    """Product data for video content."""
    id: str
    title: str
    category: str
    features: list[str]
    price: float
    unique_selling_points: list[str]


class BrandVoice(TypedDict, total=False):
    """Brand voice configuration."""
    tone: str
    style: str
    audience: str
    brand_name: str


class VideoInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: ProductInfo
    platform: str
    video_type: str
    duration_seconds: int
    brand_voice: BrandVoice


# ---------------------------------------------------------------------------
# Intermediate types — script writing
# ---------------------------------------------------------------------------

class ScriptSection(TypedDict):
    """A section of a video script."""
    section: str
    content: str
    duration_seconds: int


class GeneratedScript(TypedDict):
    """Generated script from script_writer."""
    hook: str
    body: str
    cta: str
    duration: int


# ---------------------------------------------------------------------------
# Intermediate types — storyboard
# ---------------------------------------------------------------------------

class StoryboardScene(TypedDict):
    """Single scene in a storyboard from storyboard_planner."""
    scene: int
    visual: str
    audio: str
    duration: int


# ---------------------------------------------------------------------------
# Intermediate types — platform optimization
# ---------------------------------------------------------------------------

class PlatformSpecs(TypedDict):
    """Platform-specific specs from platform_optimizer."""
    platform: str
    aspect_ratio: str
    max_duration: int
    min_resolution: str
    recommended_hashtags: list[str]
    best_posting_times: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — performance estimation
# ---------------------------------------------------------------------------

class EngagementEstimate(TypedDict):
    """Estimated engagement from performance_estimator."""
    estimated_views: int
    estimated_likes: int
    estimated_comments: int
    estimated_shares: int
    engagement_rate: float
    confidence: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class VideoOutputData(TypedDict):
    """The 'data' block of the engine output."""
    script: GeneratedScript
    storyboard: list[StoryboardScene]
    platform_specs: PlatformSpecs
    estimated_engagement: EngagementEstimate


class VideoMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class VideoOutput(TypedDict):
    """Final output of the video marketing engine."""
    status: str
    data: VideoOutputData | None
    meta: VideoMeta
    error: str | None
