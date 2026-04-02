"""Email Marketing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the email marketing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInfo(TypedDict, total=False):
    """Product to feature in the email campaign."""
    title: str
    price: float
    image_url: str


class DiscountInfo(TypedDict, total=False):
    """Discount applied to the campaign."""
    type: str          # "percentage" | "fixed"
    value: float       # e.g. 20 for 20%


class CampaignInput(TypedDict, total=False):
    """Top-level 'data' block of engine input."""
    goal: str                           # "promotional" | "nurture" | "win-back" | "announcement"
    products: list[ProductInfo]
    audience_segments: list[str]        # e.g. ["vip", "active"]
    store_name: str
    discount: DiscountInfo


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class AudienceSelection(TypedDict):
    """Result from audience_selector."""
    selected_segments: list[str]
    audience_size: int
    suppressed_count: int
    engagement_priority: list[dict[str, Any]]
    model_note: str


class ContentPlan(TypedDict):
    """Result from content_planner."""
    campaign_type: str
    sections: list[dict[str, str]]     # [{type, purpose, notes}]
    cta_strategy: str
    tone: str
    personalization_tokens: list[str]


class SubjectLineSet(TypedDict):
    """Result from subject_line_generator."""
    subject_lines: list[dict[str, Any]]   # [{text, style, personalized, emoji}]
    recommended_index: int
    model_note: str


class EmailBody(TypedDict):
    """Result from body_composer."""
    html_template: str
    headline: str
    product_blocks: list[dict[str, Any]]
    benefit_bullets: list[str]
    social_proof: str
    cta_text: str
    model_note: str


class SendTimeRecommendation(TypedDict):
    """Result from send_time_optimizer."""
    recommended_day: str
    recommended_hour: int
    timezone: str
    iso_send_time: str
    frequency_cap: str
    rationale: str


class ABVariantSet(TypedDict):
    """Result from ab_variant_builder."""
    variants: list[dict[str, Any]]
    split_ratios: list[float]
    test_metric: str
    minimum_sample_size: int


class PerformancePrediction(TypedDict):
    """Result from performance_predictor."""
    open_rate: float
    click_rate: float
    conversion_rate: float
    unsubscribe_rate: float
    confidence: float
    factors: list[str]
    model_note: str


class AssembledCampaign(TypedDict):
    """Result from campaign_assembler."""
    subject_lines: list[str]
    body_html_template: str
    audience_size: int
    send_time: str
    ab_variants: list[dict[str, Any]]
    predicted_performance: dict[str, float]
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class EmailMarketingOutput(TypedDict):
    """Final output of the email marketing engine."""
    status: str
    data: EmailMarketingData | None
    meta: EmailMarketingMeta
    error: str | None


class EmailMarketingData(TypedDict):
    """The 'data' block of the engine output."""
    campaign: AssembledCampaign
    confidence: float


class EmailMarketingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
