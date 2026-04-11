"""Product Lifecycle Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product lifecycle engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class LifecycleProduct(TypedDict, total=False):
    """Single product for lifecycle analysis."""
    id: str
    title: str
    category: str
    launch_date: str
    price: float


class SalesHistoryItem(TypedDict, total=False):
    """Single sales history record."""
    product_id: str
    period: str
    units_sold: int
    revenue: float


class LifecycleInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[LifecycleProduct]
    sales_history: list[SalesHistoryItem]


# ---------------------------------------------------------------------------
# Intermediate types — stage classification
# ---------------------------------------------------------------------------

class StageClassification(TypedDict):
    """Per-product lifecycle stage from stage_classifier."""
    product_id: str
    stage: str
    confidence: float
    indicators: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — velocity tracking
# ---------------------------------------------------------------------------

class VelocityResult(TypedDict):
    """Per-product sales velocity from velocity_tracker."""
    product_id: str
    current_velocity: float
    velocity_trend: str
    acceleration: float
    periods_analyzed: int


# ---------------------------------------------------------------------------
# Intermediate types — trend projection
# ---------------------------------------------------------------------------

class TrendProjection(TypedDict):
    """Per-product trend projection from trend_projector."""
    product_id: str
    projected_transition: str
    periods_to_transition: int
    projection_confidence: float
    growth_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — action advice
# ---------------------------------------------------------------------------

class ActionAdvice(TypedDict):
    """Per-product action advice from action_advisor."""
    product_id: str
    recommended_actions: list[str]
    priority: str
    rationale: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class LifecycleItem(TypedDict):
    """Single product lifecycle assessment in output."""
    product_id: str
    stage: str
    velocity: float
    projected_transition: str
    periods_to_transition: int
    recommended_actions: list[str]


class LifecycleData(TypedDict):
    """The 'data' block of the engine output."""
    lifecycle: list[LifecycleItem]


class LifecycleMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class LifecycleOutput(TypedDict):
    """Final output of the product lifecycle engine."""
    status: str
    data: LifecycleData | None
    meta: LifecycleMeta
    error: str | None
