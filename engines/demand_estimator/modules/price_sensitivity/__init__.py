"""Price Sensitivity module — how price changes affect demand."""
from .code import analyze_price_sensitivity, estimate_revenue_curve, estimate_profit_curve
from .logic import calculate_optimal_price, model_price_change_impact, find_price_ceiling
from .rules import evaluate_rules
from .data import PriceRecord, get_category_elasticity, get_willingness_distribution, get_competitor_impact
from .knowledge import get_pricing_insight, get_heuristics, recommend_pricing_strategy
