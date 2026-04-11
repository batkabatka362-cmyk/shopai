"""Customer Behavior Simulator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the customer behavior simulator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ProposedAction(TypedDict, total=False):
    type: str
    target_segment: str
    details: dict[str, Any]


class CustomerBehaviorInputData(TypedDict, total=False):
    customers: list[dict[str, Any]]
    proposed_actions: list[ProposedAction]
    historical_data: dict[str, Any]


class BehaviorPattern(TypedDict):
    segment: str
    avg_order_frequency: float
    avg_order_value: float
    churn_rate: float
    ltv: float
    engagement_score: float


class ActionSimulation(TypedDict):
    action: str
    target_segment: str
    predicted_retention_change: float
    predicted_ltv_change: float
    predicted_revenue_impact: float
    confidence: float


class RetentionPrediction(TypedDict):
    segment: str
    current_retention: float
    predicted_retention: float
    change_pct: float
    risk_level: str


class LTVProjection(TypedDict):
    segment: str
    current_ltv: float
    projected_ltv: float
    change_pct: float
    payback_months: float


class CustomerBehaviorData(TypedDict):
    simulations: list[ActionSimulation]
    recommended_actions: list[str]


class CustomerBehaviorMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class CustomerBehaviorOutput(TypedDict):
    status: str
    data: CustomerBehaviorData | None
    meta: CustomerBehaviorMeta
    error: str | None
