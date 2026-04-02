"""Narrative Builder Module — plain-language explanation of the selection decision.

Constructs a structured narrative that explains what was selected, why it
was selected, and how the decision was reached, using template-based
generation with no AI dependency.
"""

from .code import build_narrative
from .logic import generate_summary, generate_explanation, generate_key_points
from .rules import NARRATIVE_RULES, validate_narrative
from .data import NARRATIVE_TEMPLATES, TRANSITION_PHRASES, FORMATTING_RULES
from .knowledge import NARRATIVE_KNOWLEDGE, get_narrative_insight

__all__ = [
    "build_narrative",
    "generate_summary",
    "generate_explanation",
    "generate_key_points",
    "validate_narrative",
    "NARRATIVE_RULES",
    "NARRATIVE_TEMPLATES",
    "TRANSITION_PHRASES",
    "FORMATTING_RULES",
    "NARRATIVE_KNOWLEDGE",
    "get_narrative_insight",
]
