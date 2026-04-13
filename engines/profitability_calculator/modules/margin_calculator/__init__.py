"""Margin Calculator module — gross, contribution, net, EBITDA margin analysis."""
from .code import calculate_margins
from .logic import assess_margin_health, recommend_margin_improvement, calculate_margin_at_scale
from .rules import evaluate_rules
from .data import (
    CATEGORY_MARGIN_BENCHMARKS,
    MARGIN_TIERS,
    BUSINESS_MODEL_MARGINS,
    get_category_benchmark,
    get_tier,
)
from .knowledge import get_margin_insights, get_improvement_playbook, get_heuristics
