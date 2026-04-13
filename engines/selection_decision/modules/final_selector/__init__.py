"""Final Selector Module — makes the selection and explains why.

Takes ranked products, confidence data, and comparison results to select
the #1 pick and #2 backup. Validates the selection against constraints,
generates a decision rationale, and produces an action plan.
"""

from .code import select_final
from .logic import (
    validate_selection,
    generate_action_plan,
    calculate_expected_outcome,
)
from .rules import evaluate_selection_rules, SELECTION_RULES
from .data import (
    SELECTION_THRESHOLDS,
    ACTION_PLAN_TEMPLATES,
    EXPECTED_OUTCOME_BENCHMARKS,
)
from .knowledge import SELECTION_KNOWLEDGE, get_selection_insight

__all__ = [
    "select_final",
    "validate_selection",
    "generate_action_plan",
    "calculate_expected_outcome",
    "evaluate_selection_rules",
    "SELECTION_RULES",
    "SELECTION_THRESHOLDS",
    "ACTION_PLAN_TEMPLATES",
    "EXPECTED_OUTCOME_BENCHMARKS",
    "SELECTION_KNOWLEDGE",
    "get_selection_insight",
]
