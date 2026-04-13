"""Subscription Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the subscription engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class Subscriber(TypedDict, total=False):
    """Single subscriber record."""
    id: str
    name: str
    email: str
    plan_id: str
    status: str
    join_date: str
    last_billing_date: str
    lifetime_value: float


class SubscriptionPlan(TypedDict, total=False):
    """Subscription plan configuration."""
    id: str
    name: str
    price_monthly: float
    price_annual: float
    features: list[str]
    tier: int


class BillingRecord(TypedDict, total=False):
    """Single billing history record."""
    billing_id: str
    subscriber_id: str
    plan_id: str
    amount: float
    date: str
    status: str


class SubscriptionProduct(TypedDict, total=False):
    """Product available for subscription."""
    id: str
    title: str
    price: float
    category: str


class SubscriptionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    subscribers: list[Subscriber]
    plans: list[SubscriptionPlan]
    billing_history: list[BillingRecord]
    products: list[SubscriptionProduct]


# ---------------------------------------------------------------------------
# Intermediate types — plan design
# ---------------------------------------------------------------------------

class PlanRecommendation(TypedDict):
    """Plan recommendation from plan_designer."""
    plan_name: str
    price_monthly: float
    price_annual: float
    features: list[str]
    target_segment: str
    estimated_adoption: float


# ---------------------------------------------------------------------------
# Intermediate types — billing
# ---------------------------------------------------------------------------

class BillingSummary(TypedDict):
    """Billing summary from billing_manager."""
    total_mrr: float
    total_arr: float
    active_subscriptions: int
    past_due_count: int
    next_billing_cycle: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — churn prediction
# ---------------------------------------------------------------------------

class ChurnRisk(TypedDict):
    """Churn risk for a subscriber from churn_predictor."""
    subscriber_id: str
    risk: float
    risk_level: str
    churn_factors: list[str]
    recommended_action: str


# ---------------------------------------------------------------------------
# Intermediate types — upgrade recommendation
# ---------------------------------------------------------------------------

class UpgradeOpportunity(TypedDict):
    """Upgrade opportunity from upgrade_recommender."""
    subscriber_id: str
    current_plan: str
    recommended_plan: str
    revenue_uplift: float
    likelihood: float
    reason: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SubscriptionData(TypedDict):
    """The 'data' block of engine output."""
    plan_recommendations: list[PlanRecommendation]
    billing_summary: BillingSummary
    churn_risks: list[ChurnRisk]
    upgrade_opportunities: list[UpgradeOpportunity]
    mrr: float


class SubscriptionMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SubscriptionOutput(TypedDict):
    """Final output of the subscription engine."""
    status: str
    data: SubscriptionData | None
    meta: SubscriptionMeta
    error: str | None
