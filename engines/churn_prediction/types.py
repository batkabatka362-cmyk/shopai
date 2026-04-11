"""Churn Prediction Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the churn prediction engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerRecord(TypedDict, total=False):
    """A single customer record for churn analysis."""
    id: str
    days_since_last_purchase: int
    total_orders: int
    total_spent: float
    avg_order_value: float
    email_open_rate: float      # 0.0 – 1.0
    site_visits_30d: int
    support_tickets_90d: int
    account_age_days: int


class ChurnPredictionInput(TypedDict, total=False):
    """Top-level 'data' block of engine input."""
    customers: list[CustomerRecord]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class ExtractedFeatures(TypedDict):
    """Result from feature_extractor."""
    customer_id: str
    days_since_last: int
    order_frequency: float          # orders per 30 days
    avg_order_value: float
    total_lifetime_value: float
    email_engagement: float         # 0.0 – 1.0
    support_tickets: int


class EngagementScore(TypedDict):
    """Result from engagement_scorer."""
    email_opens_score: float        # 0.0 – 1.0
    site_visits_score: float
    cart_activity_score: float
    social_interaction_score: float
    composite_score: float          # weighted combination
    model_note: str


class RecencyAnalysis(TypedDict):
    """Result from recency_analyzer."""
    decay_score: float              # exponential decay value 0.0 – 1.0
    personal_baseline_ratio: float  # vs customer's own average
    population_ratio: float         # vs population average
    recency_risk: float             # combined risk 0.0 – 1.0


class PurchasePattern(TypedDict):
    """Result from purchase_pattern_detector."""
    frequency_change: float         # negative = declining
    aov_trend: float                # negative = declining
    category_shift: bool
    declining_engagement: bool
    pattern_risk: float             # 0.0 – 1.0
    model_note: str


class ChurnProbability(TypedDict):
    """Result from churn_probability_calculator."""
    probability: float              # 0.0 – 1.0
    factor_contributions: dict[str, float]


class RiskClassification(TypedDict):
    """Result from risk_classifier."""
    level: str                      # critical | high | medium | low | minimal
    threshold: float
    description: str


class RetentionAction(TypedDict):
    """Result from retention_recommender."""
    action: str                     # personal_outreach | win_back_offer | loyalty_reward | re-engagement_email | exclusive_access
    rationale: str
    urgency: str                    # immediate | soon | routine
    estimated_cost_tier: str        # high | medium | low
    model_note: str


# ---------------------------------------------------------------------------
# Per-customer prediction
# ---------------------------------------------------------------------------

class CustomerPrediction(TypedDict):
    """A single customer's churn prediction result."""
    customer_id: str
    churn_probability: float
    risk_level: str
    key_factors: list[str]
    retention_action: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class PredictionSummary(TypedDict):
    """Summary statistics across all predictions."""
    total_analyzed: int
    high_risk_count: int
    avg_churn_probability: float


class ChurnPredictionData(TypedDict):
    """The 'data' block of the engine output."""
    predictions: list[CustomerPrediction]
    summary: PredictionSummary
    confidence: float


class ChurnPredictionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ChurnPredictionOutput(TypedDict):
    """Final output of the churn prediction engine."""
    status: str
    data: ChurnPredictionData | None
    meta: ChurnPredictionMeta
    error: str | None
