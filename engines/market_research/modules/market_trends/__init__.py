"""Market Trends module — trend detection, timing, and sustainability analysis."""
from .code import compute_trend_score, analyze_category_trends, detect_momentum_shift
from .logic import assess_trend_timing, evaluate_trend_sustainability, should_follow_trend
from .rules import evaluate_rules
from .data import TrendSnapshot, get_known_trending, get_seasonal_modifier
from .knowledge import get_trend_lifecycle, classify_trend_stage, get_fad_patterns, get_timing_intelligence
