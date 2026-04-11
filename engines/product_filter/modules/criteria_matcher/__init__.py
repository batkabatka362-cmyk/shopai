"""
criteria_matcher — Filter products by business criteria.

Applies margin, price range, weight, category, rating, and review
filters to a product list and returns accepted / rejected splits
with detailed rejection reasons.
"""

from .code import filter_by_criteria
from .logic import (
    recommend_criteria,
    analyze_rejection_patterns,
    adjust_criteria,
)
from .rules import (
    DEFAULT_CRITERIA,
    GOAL_OVERRIDES,
    get_criteria_for_goal,
)
from .data import (
    CATEGORY_DEFAULTS,
    PRICE_BENCHMARKS,
    MARGIN_BENCHMARKS,
    get_category_criteria,
)
from .knowledge import (
    FILTERING_HEURISTICS,
    diagnose_filter_results,
    get_heuristic_warnings,
)

__all__ = [
    "filter_by_criteria",
    "recommend_criteria",
    "analyze_rejection_patterns",
    "adjust_criteria",
    "DEFAULT_CRITERIA",
    "GOAL_OVERRIDES",
    "get_criteria_for_goal",
    "CATEGORY_DEFAULTS",
    "PRICE_BENCHMARKS",
    "MARGIN_BENCHMARKS",
    "get_category_criteria",
    "FILTERING_HEURISTICS",
    "diagnose_filter_results",
    "get_heuristic_warnings",
]
