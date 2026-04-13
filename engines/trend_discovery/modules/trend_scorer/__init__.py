"""Trend Scorer module — aggregate all signals into unified trend scores."""
from .code import score_trend
from .logic import rank_trends, decide_trend_action, compare_trends, build_trend_portfolio
from .rules import evaluate_rules
from .data import SIGNAL_WEIGHTS, SCORE_THRESHOLDS, HISTORICAL_ACCURACY, PORTFOLIO_RULES
from .knowledge import get_scoring_heuristics, get_portfolio_strategy
