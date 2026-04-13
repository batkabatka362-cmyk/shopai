"""Search Volume module — estimate product demand from keyword search volume data."""
from .code import analyze_search_volume
from .logic import estimate_demand_from_search, rank_keywords_by_demand, calculate_search_market_share
from .rules import evaluate_rules
from .data import (
    CONVERSION_RATES_BY_CATEGORY,
    SEARCH_VOLUME_BENCHMARKS,
    KEYWORD_INTENT_WEIGHTS,
    SEASONAL_MULTIPLIERS,
    get_conversion_rate,
    get_seasonal_multiplier,
)
from .knowledge import get_heuristics, get_search_insight, get_platform_multiplier
