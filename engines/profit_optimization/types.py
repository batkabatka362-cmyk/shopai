"""Profit Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the profit optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SalesData(TypedDict, total=False):
    """Sales metrics from the store."""
    total_revenue: float
    units_sold: int
    orders: int
    avg_order_value: float
    refunds: int


class AdsData(TypedDict, total=False):
    """Advertising spend and performance."""
    total_spend: float
    impressions: int
    clicks: int
    conversions: int
    platform_breakdown: dict[str, float]


class CostData(TypedDict, total=False):
    """All cost line items."""
    cogs: float
    shipping: float
    platform_fees: float
    tools: float
    labor: float


class PerformanceData(TypedDict, total=False):
    """Store performance metrics."""
    conversion_rate: float
    cart_abandonment: float
    return_rate: float
    customer_satisfaction: float


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class ProfitMetrics(TypedDict):
    """Complete profit breakdown computed by profit_calculator."""
    gross_revenue: float
    refund_loss: float
    net_revenue: float
    cogs: float
    gross_profit: float
    gross_margin: float
    ad_spend: float
    shipping: float
    platform_fees: float
    tools: float
    labor: float
    total_operating_costs: float
    total_cost: float
    net_profit: float
    net_margin: float
    revenue_per_unit: float
    cost_per_unit: float
    profit_per_unit: float
    break_even_units: int
    break_even_revenue: float


class KPIResult(TypedDict):
    """KPI analysis results."""
    roas: float
    cpa: float
    clv_estimate: float
    aov: float
    conversion_rate: float
    cart_abandonment: float
    return_rate: float
    cost_per_click: float
    click_through_rate: float
    ad_conversion_rate: float
    margin_health: str
    roas_health: str
    cpa_health: str
    conversion_health: str
    abandonment_health: str
    overall_health: str
    health_score: float


class Opportunity(TypedDict):
    """A single profit optimization opportunity."""
    opportunity_id: str
    category: str
    title: str
    description: str
    estimated_impact: float
    confidence: float
    effort: str
    priority: str


class Optimization(TypedDict):
    """A specific optimization action generated from an opportunity."""
    optimization_id: str
    opportunity_id: str
    action: str
    details: str
    expected_revenue_change: float
    expected_cost_change: float
    expected_profit_change: float
    implementation_effort: str
    timeframe: str
    model_note: str


class Strategy(TypedDict):
    """Selected strategy combining multiple optimizations."""
    strategy_id: str
    name: str
    description: str
    optimization_ids: list[str]
    expected_total_profit_change: float
    expected_total_revenue_change: float
    risk_level: str
    confidence: float
    reasoning: list[str]


class ActionRecommendation(TypedDict):
    """Concrete action recommendation with priority."""
    action_id: str
    title: str
    description: str
    priority: str
    expected_impact: float
    category: str
    steps: list[str]
    timeframe: str
    model_note: str


class RiskAssessment(TypedDict):
    """Risk assessment for an optimization."""
    optimization_id: str
    financial_risk: float
    customer_impact_risk: float
    competitive_risk: float
    overall_risk: float
    risk_level: str
    mitigations: list[str]
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProfitOptimizationOutput(TypedDict):
    """Final output of the profit optimization engine."""
    status: str
    data: ProfitOptimizationData | None
    meta: ProfitOptimizationMeta
    error: str | None


class ProfitOptimizationData(TypedDict):
    """The 'data' block of the engine output."""
    profit: float
    revenue: float
    cost: float
    kpis: dict[str, Any]
    opportunities: list[dict[str, Any]]
    optimizations: list[dict[str, Any]]
    selected_strategy: dict[str, Any]
    recommended_actions: list[dict[str, Any]]
    risk_level: str
    confidence: float


class ProfitOptimizationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
