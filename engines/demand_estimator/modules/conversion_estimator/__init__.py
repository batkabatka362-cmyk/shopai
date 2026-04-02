"""Conversion Estimator module — visitor-to-buyer conversion modeling."""
from .code import estimate_conversion, estimate_funnel_throughput, estimate_daily_purchases
from .logic import optimize_funnel, estimate_conversion_improvement, benchmark_conversion
from .rules import evaluate_rules
from .data import ConversionRecord, get_category_conversion, get_source_conversion, get_abandonment_rate
from .knowledge import get_conversion_insight, get_heuristics, recommend_improvements
