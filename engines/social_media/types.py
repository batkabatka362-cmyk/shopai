"""Social Media Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the social media engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInfo(TypedDict, total=False):
    """Product to feature in social media content."""
    title: str
    category: str


class BrandInfo(TypedDict, total=False):
    """Brand identity and voice."""
    name: str
    voice: str  # "playful" | "professional" | "bold" | "minimal"


class SocialMediaInput(TypedDict, total=False):
    """Top-level 'data' block of engine input."""
    platforms: list[str]                # ["instagram", "facebook", "tiktok", ...]
    products: list[ProductInfo]
    brand: BrandInfo
    goal: str                           # "engagement" | "awareness" | "traffic" | "conversions"
    posting_frequency: str              # "daily" | "twice_daily" | "every_other_day" | "weekly"


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class PlatformAnalysis(TypedDict):
    """Result from platform_analyzer."""
    platform: str
    best_formats: list[str]
    optimal_post_frequency: int         # posts per week
    audience_behavior: str
    key_features: list[str]
    character_limit: int
    hashtag_limit: int
    model_note: str


class ContentCalendarEntry(TypedDict):
    """Single entry in the content calendar."""
    day: str                            # "monday", "tuesday", ...
    platform: str
    post_type: str                      # "reel", "carousel", "story", "pin", "thread", ...
    theme: str
    time_slot: str                      # e.g. "09:00"


class ContentCalendar(TypedDict):
    """Result from content_calendar_builder."""
    entries: list[ContentCalendarEntry]
    total_posts_per_week: int
    platform_breakdown: dict[str, int]
    model_note: str


class PostContent(TypedDict):
    """Result from post_creator."""
    platform: str
    post_type: str
    caption: str
    visual_description: str
    cta: str
    formatting_notes: str
    model_note: str


class HashtagSet(TypedDict):
    """Result from hashtag_generator."""
    platform: str
    trending: list[str]
    niche: list[str]
    branded: list[str]
    ranked: list[dict[str, Any]]        # [{tag, volume_score}]


class EngagementPrediction(TypedDict):
    """Result from engagement_predictor."""
    platform: str
    predicted_likes: int
    predicted_comments: int
    predicted_shares: int
    predicted_saves: int
    engagement_rate: float
    confidence: float
    model_note: str


class ScheduleSlot(TypedDict):
    """Single optimized posting slot."""
    platform: str
    day: str
    time: str
    priority: str                       # "high" | "medium" | "low"


class OptimizedSchedule(TypedDict):
    """Result from schedule_optimizer."""
    slots: list[ScheduleSlot]
    conflicts_resolved: int
    frequency_caps: dict[str, int]
    model_note: str


class PerformanceReport(TypedDict):
    """Result from performance_analyzer."""
    engagement_rate: float
    reach_estimate: int
    follower_growth_rate: float
    best_performing_type: str
    best_performing_platform: str
    recommendations: list[str]
    model_note: str


class TrendingItem(TypedDict):
    """Single trending topic/format from trend_tracker."""
    platform: str
    topic: str
    category: str                       # "sound" | "format" | "hashtag" | "challenge"
    relevance_score: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SocialMediaOutput(TypedDict):
    """Final output of the social media engine."""
    status: str
    data: SocialMediaData | None
    meta: SocialMediaMeta
    error: str | None


class SocialMediaData(TypedDict):
    """The 'data' block of the engine output."""
    content_calendar: list[ContentCalendarEntry]
    posts: list[PostContent]
    schedule: OptimizedSchedule
    predicted_engagement: dict[str, Any]
    trending: list[TrendingItem]
    confidence: float


class SocialMediaMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
