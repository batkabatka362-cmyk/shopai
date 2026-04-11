"""Seasonality module — seasonal pattern detection, timing, and planning."""
from .code import compute_seasonality_profile, compute_event_calendar, compute_optimal_launch_window
from .logic import plan_seasonal_strategy, calculate_inventory_multiplier, calculate_ad_spend_multiplier, should_launch_now
from .rules import evaluate_rules
from .data import get_seasonal_pattern, get_weekly_pattern, get_payday_effects, list_all_categories, CATEGORY_SEASONAL_PATTERNS
from .knowledge import get_timing_rules, get_category_timing, get_cash_flow_guidance, get_prep_checklist
