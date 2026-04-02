"""Score Aggregator Module — combines scores from all upstream engines.

Aggregates market research, trend discovery, profitability, competition,
demand, risk, and filter engine outputs into a unified product score
using weighted normalization and conflict detection.
"""

from .code import aggregate_scores
from .logic import (
    customize_weights,
    detect_score_conflicts,
    compute_weighted_score,
)
from .rules import validate_aggregation_inputs, AGGREGATION_RULES
from .data import (
    DEFAULT_WEIGHTS,
    GOAL_WEIGHT_PROFILES,
    NORMALIZATION_RANGES,
    CONFLICT_THRESHOLDS,
    MINIMUM_CONFIDENCE,
)
from .knowledge import AGGREGATION_KNOWLEDGE, get_aggregation_insight

__all__ = [
    "aggregate_scores",
    "customize_weights",
    "detect_score_conflicts",
    "compute_weighted_score",
    "validate_aggregation_inputs",
    "AGGREGATION_RULES",
    "DEFAULT_WEIGHTS",
    "GOAL_WEIGHT_PROFILES",
    "NORMALIZATION_RANGES",
    "CONFLICT_THRESHOLDS",
    "MINIMUM_CONFIDENCE",
    "AGGREGATION_KNOWLEDGE",
    "get_aggregation_insight",
]
