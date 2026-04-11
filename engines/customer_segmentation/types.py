"""Customer Segmentation Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the customer segmentation engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerRecord(TypedDict, total=False):
    """A single customer record from the input payload."""
    id: str
    first_purchase: str
    last_purchase: str
    total_orders: int
    total_spent: float
    avg_order_value: float
    days_since_last: int
    categories_bought: list[str]
    email_opens: int
    cart_abandons: int


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class NormalizedCustomer(TypedDict):
    """Customer record after normalization — all fields guaranteed."""
    id: str
    first_purchase: str
    last_purchase: str
    total_orders: int
    total_spent: float
    avg_order_value: float
    days_since_last: int
    categories_bought: list[str]
    email_opens: int
    cart_abandons: int
    tenure_days: int


class RFMScores(TypedDict):
    """RFM scores for a single customer."""
    customer_id: str
    recency_score: int
    frequency_score: int
    monetary_score: int
    rfm_composite: int
    rfm_segment: str


class BehavioralCluster(TypedDict):
    """Behavioral cluster assignment for a customer."""
    customer_id: str
    cluster: str
    browse_intensity: str
    cart_behavior: str
    purchase_timing: str
    channel_preference: str


class LifecycleStage(TypedDict):
    """Lifecycle classification for a customer."""
    customer_id: str
    stage: str
    confidence: float
    signals: list[str]


class ValueScore(TypedDict):
    """Customer lifetime value scoring."""
    customer_id: str
    historical_clv: float
    predicted_future_clv: float
    total_clv: float
    value_tier: str


class ChurnPrediction(TypedDict):
    """Churn prediction for a customer."""
    customer_id: str
    churn_probability: float
    risk_level: str
    decay_factor: float
    engagement_score: float
    days_until_likely_churn: int


class CustomerSegment(TypedDict):
    """A final customer segment."""
    name: str
    size: int
    customers: list[str]
    avg_clv: float
    strategy: str


class SegmentStrategy(TypedDict):
    """Marketing strategy mapped to a segment."""
    segment_name: str
    strategy_type: str
    description: str
    tactics: list[str]
    priority: str
    expected_impact: str
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SegmentationOutput(TypedDict):
    """Final output of the customer segmentation engine."""
    status: str
    data: SegmentationData | None
    meta: SegmentationMeta
    error: str | None


class SegmentationData(TypedDict):
    """The 'data' block of the engine output."""
    segments: list[dict[str, Any]]
    segment_distribution: dict[str, int]
    high_value_count: int
    at_risk_count: int
    churn_predictions: list[dict[str, Any]]


class SegmentationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
    total_customers: int
