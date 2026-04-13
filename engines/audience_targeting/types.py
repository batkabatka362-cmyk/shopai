"""Audience Targeting Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the audience targeting engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerRecord(TypedDict, total=False):
    """Single customer record."""
    id: str
    email: str
    total_orders: int
    total_spent: float
    last_order_date: str
    tags: list[str]
    location: str
    age_group: str


class OrderRecord(TypedDict, total=False):
    """Single order record."""
    id: str
    customer_id: str
    total: float
    date: str
    products: list[str]
    channel: str


class SegmentDefinition(TypedDict, total=False):
    """A pre-defined audience segment."""
    id: str
    name: str
    rules: list[dict[str, Any]]
    description: str


class AudienceInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    customers: list[CustomerRecord]
    orders: list[OrderRecord]
    segments: list[SegmentDefinition]
    campaign_goal: str


# ---------------------------------------------------------------------------
# Intermediate types — segment building
# ---------------------------------------------------------------------------

class BuiltSegment(TypedDict):
    """A segment built from customer data."""
    segment_id: str
    name: str
    description: str
    customer_ids: list[str]
    size: int
    criteria: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — rule matching
# ---------------------------------------------------------------------------

class RuleMatchResult(TypedDict):
    """Result of matching customers against segment rules."""
    segment_id: str
    name: str
    matched_customer_ids: list[str]
    match_count: int
    match_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — size estimation
# ---------------------------------------------------------------------------

class SizeEstimate(TypedDict):
    """Estimated reachable audience size for a segment."""
    segment_id: str
    name: str
    matched_size: int
    estimated_reachable: int
    reachability_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — lookalike building
# ---------------------------------------------------------------------------

class LookalikeAudience(TypedDict):
    """A lookalike audience derived from a seed segment."""
    segment_id: str
    name: str
    seed_size: int
    lookalike_size: int
    similarity_score: float
    lookalike_customer_ids: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class AudienceResult(TypedDict):
    """Single audience in the output."""
    name: str
    size: int
    criteria: dict[str, Any]
    match_rate: float


class AudienceOutputData(TypedDict):
    """The 'data' block of engine output."""
    audiences: list[AudienceResult]
    recommended_audience: str
    total_reachable: int


class AudienceMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AudienceOutput(TypedDict):
    """Final output of the audience targeting engine."""
    status: str
    data: AudienceOutputData | None
    meta: AudienceMeta
    error: str | None
