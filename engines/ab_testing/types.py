"""A/B Testing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the A/B testing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ABTestInput(TypedDict, total=False):
    """Raw input payload arriving at the engine."""
    status: str
    data: ABTestInputData
    meta: dict[str, Any]
    error: str | None


class ABTestInputData(TypedDict, total=False):
    """The 'data' block inside the input payload."""
    test_type: str                  # "pricing", "content", "ads", "ux"
    hypothesis: str                 # human-readable hypothesis
    control: dict[str, Any]         # control variant parameters
    treatment: dict[str, Any]       # treatment variant parameters
    primary_metric: str             # "conversion_rate", "revenue_per_visitor", etc.
    guardrail_metrics: list[str]    # metrics that must not degrade
    current_rate: float             # baseline rate for primary metric
    mde: float                      # minimum detectable effect (absolute)
    daily_traffic: int              # daily visitors available for test
    alpha: float                    # significance level (default 0.05)
    power: float                    # statistical power (default 0.80)
    test_duration_days: int         # override for test duration
    segments: list[str]             # audience segments to analyze
    history: list[dict[str, Any]]   # past test results for memory


# ---------------------------------------------------------------------------
# Experiment types
# ---------------------------------------------------------------------------

class ExperimentDesign(TypedDict):
    """Designed experiment output from experiment_designer."""
    test_id: str
    test_type: str
    hypothesis: str
    null_hypothesis: str
    primary_metric: str
    guardrail_metrics: list[str]
    control_description: str
    treatment_description: str
    test_methodology: str           # "two-sample z-test", "two-sample t-test"
    expected_direction: str         # "increase", "decrease"
    model_note: str


# ---------------------------------------------------------------------------
# Sample size types
# ---------------------------------------------------------------------------

class SampleSizeResult(TypedDict):
    """Output from sample_size_calculator."""
    sample_size_per_variant: int
    total_sample_size: int
    baseline_rate: float
    mde: float
    alpha: float
    power: float
    estimated_days: int
    daily_traffic_per_variant: int


# ---------------------------------------------------------------------------
# Variant types
# ---------------------------------------------------------------------------

class Variant(TypedDict):
    """A single test variant (control or treatment)."""
    variant_id: str
    variant_name: str               # "control", "treatment_a", etc.
    is_control: bool
    parameters: dict[str, Any]
    description: str
    changes_from_control: list[str]


# ---------------------------------------------------------------------------
# Traffic split types
# ---------------------------------------------------------------------------

class TrafficSplit(TypedDict):
    """Traffic allocation configuration."""
    num_variants: int
    splits: dict[str, float]        # variant_id -> fraction (e.g. 0.50)
    daily_visitors_per_variant: int
    minimum_traffic_met: bool
    allocation_method: str          # "equal", "weighted"


# ---------------------------------------------------------------------------
# Metric types
# ---------------------------------------------------------------------------

class VariantMetrics(TypedDict):
    """Collected metrics for a single variant."""
    variant_id: str
    variant_name: str
    visitors: int
    conversions: int
    conversion_rate: float
    revenue: float
    revenue_per_visitor: float
    bounce_rate: float
    time_on_page: float             # seconds


# ---------------------------------------------------------------------------
# Statistical analysis types
# ---------------------------------------------------------------------------

class StatisticalResult(TypedDict):
    """Output from statistical_analyzer."""
    test_statistic: float           # z-score or t-statistic
    p_value: float
    confidence_interval: tuple[float, float]
    effect_size: float              # absolute difference
    relative_effect: float          # percentage lift
    power_achieved: float
    significant: bool
    method: str                     # "z-test" or "t-test"
    model_note: str


# ---------------------------------------------------------------------------
# Winner types
# ---------------------------------------------------------------------------

class WinnerResult(TypedDict):
    """Output from winner_selector."""
    winner: str                     # variant_id or "no_winner"
    winner_name: str
    reason: str
    statistically_significant: bool
    practically_significant: bool
    sample_sufficient: bool
    recommendation: str             # "implement", "extend_test", "stop_test"
    confidence: float


# ---------------------------------------------------------------------------
# Risk types
# ---------------------------------------------------------------------------

class RiskAssessment(TypedDict):
    """Risk assessment for implementing the winner."""
    overall_risk: float             # 0.0-1.0
    risk_level: str                 # "low", "medium", "high"
    novelty_effect_risk: float      # 0.0-1.0
    segment_risk: float             # 0.0-1.0
    long_term_risk: float           # 0.0-1.0
    risk_factors: list[RiskFactor]
    mitigation_suggestions: list[str]
    model_note: str


class RiskFactor(TypedDict):
    """Individual risk factor."""
    name: str
    severity: float                 # 0.0-1.0
    likelihood: float               # 0.0-1.0
    description: str


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------

class TestRecord(TypedDict, total=False):
    """A stored test result record."""
    record_id: str
    timestamp: str
    test_type: str
    input_hash: str
    experiment: ExperimentDesign
    winner: WinnerResult
    analysis: StatisticalResult
    confidence: float
    outcome_actual: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ABTestOutput(TypedDict):
    """Final output of the A/B testing engine."""
    status: str
    data: ABTestOutputData | None
    meta: ABTestMeta
    error: str | None


class ABTestOutputData(TypedDict):
    """The 'data' block of the engine output."""
    experiment: ExperimentDesign
    sample_size: int
    variants: list[Variant]
    traffic_split: TrafficSplit
    metrics: list[VariantMetrics]
    analysis: dict[str, Any]        # p_value, confidence_interval, effect_size, power
    winner: WinnerResult
    risk: RiskAssessment
    confidence: float


class ABTestMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    test_type: str
    timestamp: str
    elapsed_seconds: float
