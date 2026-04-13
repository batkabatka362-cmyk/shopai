"""Demand Trend module — analyze whether demand is growing, stable, or declining."""
from .code import analyze_demand_trend
from .logic import (
    predict_demand_trajectory,
    detect_demand_ceiling,
    assess_demand_sustainability,
)
from .rules import evaluate_rules
from .data import (
    TREND_VELOCITY_BENCHMARKS,
    CATEGORY_LIFECYCLE_POSITIONS,
    SEASONAL_ADJUSTMENT_FACTORS,
    DEMAND_CEILING_INDICATORS,
    get_velocity_benchmark,
    get_lifecycle_position,
)
from .knowledge import get_heuristics, get_trend_insight, get_market_stage_advice
