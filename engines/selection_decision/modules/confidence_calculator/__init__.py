"""Confidence Calculator Module — quantifies certainty in selection decisions.

Evaluates data quality, signal agreement, historical accuracy, and score gaps
to produce a composite confidence rating (low/medium/high) that governs
whether the decision auto-proceeds, proceeds with monitoring, or requires
human review.
"""

from .code import calculate_confidence
from .logic import (
    assess_data_completeness,
    measure_signal_agreement,
    calibrate_confidence,
)
from .rules import evaluate_confidence_rules, CONFIDENCE_RULES
from .data import (
    CONFIDENCE_WEIGHTS,
    CALIBRATION_BENCHMARKS,
    HISTORICAL_ACCURACY_BASELINES,
    SIGNAL_AGREEMENT_THRESHOLDS,
)
from .knowledge import CONFIDENCE_KNOWLEDGE, get_confidence_insight

__all__ = [
    "calculate_confidence",
    "assess_data_completeness",
    "measure_signal_agreement",
    "calibrate_confidence",
    "evaluate_confidence_rules",
    "CONFIDENCE_RULES",
    "CONFIDENCE_WEIGHTS",
    "CALIBRATION_BENCHMARKS",
    "HISTORICAL_ACCURACY_BASELINES",
    "SIGNAL_AGREEMENT_THRESHOLDS",
    "CONFIDENCE_KNOWLEDGE",
    "get_confidence_insight",
]
