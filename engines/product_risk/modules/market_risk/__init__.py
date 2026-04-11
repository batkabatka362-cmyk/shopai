"""Market Risk module — saturation, demand, and competitive threat assessment."""
from .code import assess_market_risk
from .logic import identify_top_risks, recommend_risk_mitigation, calculate_risk_adjusted_opportunity
from .rules import evaluate_rules
from .data import (
    RISK_THRESHOLDS,
    MATURITY_RISK_PROFILES,
    COMPETITIVE_INTENSITY_BENCHMARKS,
    get_price_erosion_rate,
)
from .knowledge import get_market_risk_insights, get_heuristics
