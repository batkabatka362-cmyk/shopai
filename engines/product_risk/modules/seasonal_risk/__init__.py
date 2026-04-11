"""Seasonal Risk module — demand volatility, cash flow gaps, and inventory timing."""
from .code import assess_seasonal_risk
from .logic import (
    calculate_cash_reserve_needed,
    assess_fad_risk,
    recommend_seasonal_strategy,
)
from .rules import evaluate_rules
from .data import (
    SEASONALITY_PROFILES,
    CASH_RESERVE_REQUIREMENTS,
    FAD_DURATION_BENCHMARKS,
    WEATHER_IMPACT_FACTORS,
    get_category_seasonality,
)
from .knowledge import get_seasonal_risk_insights, get_heuristics
