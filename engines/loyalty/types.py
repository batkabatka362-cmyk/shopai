"""Loyalty Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the loyalty engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerRecord(TypedDict, total=False):
    """Single customer record."""
    customer_id: str
    name: str
    email: str
    total_spent: float
    order_count: int
    joined_date: str


class OrderRecord(TypedDict, total=False):
    """Single order record."""
    order_id: str
    customer_id: str
    total: float
    items: list[dict[str, Any]]
    date: str


class ProgramConfig(TypedDict, total=False):
    """Loyalty program configuration."""
    points_per_dollar: float
    tier_thresholds: dict[str, int]
    reward_catalog: list[dict[str, Any]]


class LoyaltyInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    customers: list[CustomerRecord]
    orders: list[OrderRecord]
    program_config: ProgramConfig
    current_points: dict[str, int]


# ---------------------------------------------------------------------------
# Intermediate types — program design
# ---------------------------------------------------------------------------

class TierDefinition(TypedDict):
    """Single tier definition from program_designer."""
    name: str
    min_points: int
    multiplier: float
    benefits: list[str]


class ProgramDesign(TypedDict):
    """Program design output from program_designer."""
    tiers: list[TierDefinition]
    point_rules: list[dict[str, Any]]
    earning_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — points calculation
# ---------------------------------------------------------------------------

class CustomerPoints(TypedDict):
    """Per-customer points calculation from points_calculator."""
    customer_id: str
    points_earned: int
    points_redeemed: int
    points_balance: int
    lifetime_points: int


# ---------------------------------------------------------------------------
# Intermediate types — tier management
# ---------------------------------------------------------------------------

class CustomerTierStatus(TypedDict):
    """Per-customer tier status from tier_manager."""
    customer_id: str
    current_tier: str
    points: int
    next_tier: str
    next_tier_progress: float
    points_to_next_tier: int


# ---------------------------------------------------------------------------
# Intermediate types — reward recommendation
# ---------------------------------------------------------------------------

class RewardRecommendation(TypedDict):
    """Per-customer reward recommendation from reward_recommender."""
    customer_id: str
    recommended_rewards: list[dict[str, Any]]
    reason: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProgramOutput(TypedDict):
    """Program structure in engine output."""
    tiers: list[TierDefinition]
    point_rules: list[dict[str, Any]]


class ProgramHealth(TypedDict):
    """Program health metrics."""
    total_members: int
    active_members: int
    total_points_outstanding: int
    avg_points_per_member: float
    tier_distribution: dict[str, int]


class LoyaltyData(TypedDict):
    """The 'data' block of the engine output."""
    program: ProgramOutput
    customer_status: list[CustomerTierStatus]
    reward_recommendations: list[RewardRecommendation]
    program_health: ProgramHealth


class LoyaltyMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class LoyaltyOutput(TypedDict):
    """Final output of the loyalty engine."""
    status: str
    data: LoyaltyData | None
    meta: LoyaltyMeta
    error: str | None
