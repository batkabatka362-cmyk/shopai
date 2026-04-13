"""Influencer Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the influencer engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class TargetAudience(TypedDict, total=False):
    """Target audience specification."""
    age_range: list[int]
    interests: list[str]
    platforms: list[str]
    geography: list[str]


class InfluencerInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    category: str
    target_audience: TargetAudience
    budget: float
    campaign_type: str


# ---------------------------------------------------------------------------
# Intermediate types — influencer finding
# ---------------------------------------------------------------------------

class InfluencerCandidate(TypedDict):
    """Influencer candidate from influencer_finder."""
    id: str
    name: str
    platform: str
    followers: int
    niche: str
    engagement_rate: float
    avg_views: int
    location: str


# ---------------------------------------------------------------------------
# Intermediate types — scoring
# ---------------------------------------------------------------------------

class ScoredInfluencer(TypedDict):
    """Scored influencer from scoring_engine."""
    id: str
    name: str
    platform: str
    followers: int
    engagement_rate: float
    score: float
    audience_fit: float
    authenticity_score: float
    estimated_cost: float


# ---------------------------------------------------------------------------
# Intermediate types — campaign plan
# ---------------------------------------------------------------------------

class CampaignPlan(TypedDict):
    """Campaign plan from campaign_planner."""
    campaign_name: str
    duration_days: int
    total_budget: float
    influencer_allocations: list[dict[str, Any]]
    content_types: list[str]
    estimated_reach: int
    estimated_conversions: int


# ---------------------------------------------------------------------------
# Intermediate types — outreach
# ---------------------------------------------------------------------------

class OutreachTemplate(TypedDict):
    """Outreach message template from outreach_builder."""
    influencer_id: str
    influencer_name: str
    subject: str
    message: str
    channel: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class InfluencerData(TypedDict):
    """The 'data' block of engine output."""
    influencers: list[ScoredInfluencer]
    campaign_plan: CampaignPlan
    estimated_roi: float
    outreach_templates: list[OutreachTemplate]


class InfluencerMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class InfluencerOutput(TypedDict):
    """Final output of the influencer engine."""
    status: str
    data: InfluencerData | None
    meta: InfluencerMeta
    error: str | None
