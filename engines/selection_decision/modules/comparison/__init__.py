"""Comparison Module — head-to-head product analysis across all dimensions.

Produces side-by-side comparisons of top 2-5 products, identifies
advantages/disadvantages per product, analyzes trade-offs, and declares
a winner per dimension (profitability, demand, risk, trend, competition).
"""

from .code import compare_products
from .logic import (
    identify_tradeoffs,
    recommend_best_for_goal,
    create_comparison_matrix,
)
from .rules import evaluate_comparison_rules, COMPARISON_RULES
from .data import (
    DIMENSION_WEIGHTS,
    TRADEOFF_TEMPLATES,
    DECISION_MATRIX_FORMAT,
)
from .knowledge import COMPARISON_KNOWLEDGE, get_comparison_insight

__all__ = [
    "compare_products",
    "identify_tradeoffs",
    "recommend_best_for_goal",
    "create_comparison_matrix",
    "evaluate_comparison_rules",
    "COMPARISON_RULES",
    "DIMENSION_WEIGHTS",
    "TRADEOFF_TEMPLATES",
    "DECISION_MATRIX_FORMAT",
    "COMPARISON_KNOWLEDGE",
    "get_comparison_insight",
]
