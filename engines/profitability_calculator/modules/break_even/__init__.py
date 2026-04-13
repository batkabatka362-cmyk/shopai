"""Break-Even Module — calculates how many units to sell to recover investment.

Covers all launch costs: inventory, marketing, setup (photography, listing),
samples. Includes sensitivity analysis for price and volume changes, plus
timeline estimation based on daily sales velocity.
"""

from .code import calculate_break_even
from .logic import (
    assess_break_even_feasibility,
    recommend_launch_budget,
    calculate_payback_period,
)
from .rules import evaluate_break_even_rules, BREAK_EVEN_RULES
from .data import (
    LAUNCH_COSTS_BY_PRODUCT_TYPE,
    DAILY_SALES_VELOCITY_BY_CATEGORY,
    SETUP_COST_BENCHMARKS,
)
from .knowledge import BREAK_EVEN_KNOWLEDGE, get_break_even_insight

__all__ = [
    "calculate_break_even",
    "assess_break_even_feasibility",
    "recommend_launch_budget",
    "calculate_payback_period",
    "evaluate_break_even_rules",
    "BREAK_EVEN_RULES",
    "LAUNCH_COSTS_BY_PRODUCT_TYPE",
    "DAILY_SALES_VELOCITY_BY_CATEGORY",
    "SETUP_COST_BENCHMARKS",
    "BREAK_EVEN_KNOWLEDGE",
    "get_break_even_insight",
]
