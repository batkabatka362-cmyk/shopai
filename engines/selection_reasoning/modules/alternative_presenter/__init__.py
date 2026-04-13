"""Alternative Presenter Module — shows what other options were considered.

Presents the top 2-3 alternatives that were evaluated, explains why they
ranked lower, and identifies close seconds worth revisiting if the
primary selection underperforms.
"""

from .code import present_alternatives
from .logic import compare_to_selection, explain_rejection_reason
from .rules import ALTERNATIVE_RULES, validate_alternatives
from .data import COMPARISON_TEMPLATES, REJECTION_CATEGORIES
from .knowledge import ALTERNATIVE_KNOWLEDGE, get_alternative_insight

__all__ = [
    "present_alternatives",
    "compare_to_selection",
    "explain_rejection_reason",
    "ALTERNATIVE_RULES",
    "validate_alternatives",
    "COMPARISON_TEMPLATES",
    "REJECTION_CATEGORIES",
    "ALTERNATIVE_KNOWLEDGE",
    "get_alternative_insight",
]
