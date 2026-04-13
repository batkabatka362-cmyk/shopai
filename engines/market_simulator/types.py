"""Market Simulator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the market simulator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class Scenario(TypedDict, total=False):
    name: str
    price_change_pct: float
    marketing_spend: float


class MarketSimulatorInputData(TypedDict, total=False):
    product: dict[str, Any]
    scenarios: list[Scenario]
    market_data: dict[str, Any]


class DemandModel(TypedDict):
    product_id: str
    base_demand: float
    price_elasticity: float
    marketing_sensitivity: float
    demand_curve: list[dict[str, float]]
    confidence: float


class PriceImpact(TypedDict):
    scenario: str
    price_change_pct: float
    demand_change_pct: float
    predicted_revenue: float
    predicted_units: float
    margin_impact: float


class LaunchSimulation(TypedDict):
    scenario: str
    adoption_curve: list[dict[str, float]]
    predicted_first_month_units: float
    predicted_first_quarter_revenue: float
    market_share_estimate: float


class ScenarioComparison(TypedDict):
    scenario: str
    predicted_revenue: float
    predicted_units: float
    confidence: float
    risk_score: float
    rank: int


class RiskAnalysis(TypedDict):
    worst_case_revenue: float
    best_case_revenue: float
    volatility_score: float
    risk_factors: list[str]


class SimulationResult(TypedDict):
    scenario: str
    predicted_revenue: float
    predicted_units: float
    confidence: float


class MarketSimulatorData(TypedDict):
    simulations: list[SimulationResult]
    best_scenario: str
    risk_analysis: RiskAnalysis


class MarketSimulatorMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class MarketSimulatorOutput(TypedDict):
    status: str
    data: MarketSimulatorData | None
    meta: MarketSimulatorMeta
    error: str | None
