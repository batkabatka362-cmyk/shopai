"""Saturation module — market overcrowding detection and entry strategy."""
from .code import analyze_saturation
from .logic import decide_entry_strategy, find_sub_niche_opportunities, assess_exit_signals
from .rules import evaluate_rules
from .data import SaturationRecord, get_category_benchmark, get_cpc_benchmark, CATEGORY_SATURATION_BENCHMARKS
from .knowledge import get_saturated_strategies, get_death_trap_signs, get_lifecycle_position, recommend_strategy_for_level
