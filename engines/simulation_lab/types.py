"""Simulation Lab — all TypedDicts and type aliases.

Single source of truth for every data shape in the simulation lab engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SimulationInput(TypedDict, total=False):
    """Raw input payload arriving at the engine."""
    status: str
    data: SimulationInputData
    meta: dict[str, Any]
    error: str | None


class SimulationInputData(TypedDict, total=False):
    """The 'data' block inside the input payload."""
    strategy_type: str              # e.g. "pricing", "inventory", "marketing"
    base_parameters: dict[str, Any] # parameters to test
    constraints: dict[str, Any]     # hard constraints (budget, min margin, etc.)
    objectives: list[str]           # what to optimize: ["revenue", "profit", "growth"]
    num_scenarios: int              # how many scenarios to generate (default 5)
    iterations_per_scenario: int    # Monte Carlo iterations per scenario (default 200)
    environment: EnvironmentConfig  # market/store environment overrides
    history: list[dict[str, Any]]   # past simulation results for memory


class EnvironmentConfig(TypedDict, total=False):
    """Environment overrides for the simulation."""
    season: str                     # "spring", "summer", "fall", "winter"
    competition_level: float        # 0.0–1.0
    demand_trend: str               # "rising", "stable", "declining"
    market_volatility: float        # 0.0–1.0
    store_maturity: str             # "new", "growing", "established"


# ---------------------------------------------------------------------------
# Scenario types
# ---------------------------------------------------------------------------

class Scenario(TypedDict):
    """A single test scenario produced by the scenario generator."""
    scenario_id: str
    label: str
    description: str
    parameters: dict[str, Any]
    variation_type: str             # "baseline", "aggressive", "conservative", "edge_case", "alternative"
    tags: list[str]


# ---------------------------------------------------------------------------
# Simulation result types
# ---------------------------------------------------------------------------

class IterationResult(TypedDict):
    """Result of a single Monte Carlo iteration."""
    iteration: int
    revenue: float
    profit: float
    units_sold: int
    cost: float
    margin: float


class SimulationResult(TypedDict):
    """Aggregated result of all iterations for one scenario."""
    scenario_id: str
    iterations: int
    mean_revenue: float
    mean_profit: float
    mean_units_sold: float
    mean_cost: float
    mean_margin: float
    std_revenue: float
    std_profit: float
    revenue_p5: float
    revenue_p50: float
    revenue_p95: float
    profit_p5: float
    profit_p50: float
    profit_p95: float
    raw_iterations: list[IterationResult]


# ---------------------------------------------------------------------------
# Environment model output
# ---------------------------------------------------------------------------

class EnvironmentFactors(TypedDict):
    """Computed environment multipliers and adjustments."""
    seasonality_multiplier: float
    competition_pressure: float
    demand_elasticity: float
    volatility_factor: float
    maturity_modifier: float
    combined_modifier: float


# ---------------------------------------------------------------------------
# Prediction types
# ---------------------------------------------------------------------------

class OutcomePrediction(TypedDict):
    """Predicted outcomes for a single scenario."""
    scenario_id: str
    predicted_revenue: float
    predicted_profit: float
    predicted_risk: float
    predicted_roi: float
    revenue_range: tuple[float, float]
    profit_range: tuple[float, float]
    confidence: float


# ---------------------------------------------------------------------------
# Analysis types
# ---------------------------------------------------------------------------

class AnalysisResult(TypedDict):
    """Analysis of patterns across simulation results."""
    scenario_id: str
    strengths: list[str]
    weaknesses: list[str]
    patterns: list[str]
    stability_score: float          # 0.0–1.0, how consistent are the results
    upside_potential: float
    downside_risk: float


# ---------------------------------------------------------------------------
# Risk types
# ---------------------------------------------------------------------------

class RiskAssessment(TypedDict):
    """Risk assessment for a single scenario."""
    scenario_id: str
    overall_risk: float             # 0.0–1.0
    risk_category: str              # "low", "medium", "high", "critical"
    risk_factors: list[RiskFactor]
    max_loss_estimate: float
    probability_of_loss: float


class RiskFactor(TypedDict):
    """Individual risk factor."""
    name: str
    severity: float                 # 0.0–1.0
    likelihood: float               # 0.0–1.0
    description: str


# ---------------------------------------------------------------------------
# Performance types
# ---------------------------------------------------------------------------

class PerformanceEstimate(TypedDict):
    """Performance estimate for a single scenario."""
    scenario_id: str
    expected_revenue: float
    expected_profit: float
    expected_roi: float
    expected_margin: float
    growth_potential: float         # 0.0–1.0
    scalability_score: float        # 0.0–1.0
    time_to_breakeven_days: float


# ---------------------------------------------------------------------------
# Comparison types
# ---------------------------------------------------------------------------

class ComparisonEntry(TypedDict):
    """Side-by-side comparison entry for one scenario."""
    scenario_id: str
    label: str
    rank: int
    scores: dict[str, float]       # objective → score
    total_score: float
    pros: list[str]
    cons: list[str]


# ---------------------------------------------------------------------------
# Selection types
# ---------------------------------------------------------------------------

class BestOption(TypedDict):
    """The selected best option with justification."""
    scenario_id: str
    label: str
    parameters: dict[str, Any]
    total_score: float
    predicted_revenue: float
    predicted_profit: float
    risk_level: str
    confidence: float
    reasoning: list[str]
    model_note: str                 # which model would be used


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------

class MemoryRecord(TypedDict, total=False):
    """A stored simulation record."""
    record_id: str
    timestamp: str
    strategy_type: str
    input_hash: str
    best_option: BestOption
    all_scenarios: list[Scenario]
    confidence: float
    outcome_actual: dict[str, Any] | None  # filled in later if tracked


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SimulationLabOutput(TypedDict):
    """Final output of the simulation lab engine."""
    status: str
    data: SimulationLabData | None
    meta: SimulationLabMeta
    error: str | None


class SimulationLabData(TypedDict):
    """The 'data' block of the engine output."""
    best_option: BestOption
    all_scenarios: list[dict[str, Any]]
    risk_assessment: dict[str, Any]
    performance_forecast: dict[str, Any]
    confidence: float


class SimulationLabMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    scenarios_tested: int
    iterations_per_scenario: int
    timestamp: str
    elapsed_seconds: float
