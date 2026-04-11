"""Narrative Builder Module — builds plain-language selection explanations.

Generates a structured narrative explaining why a product was selected,
including a one-sentence summary, multi-paragraph explanation, and
bullet-point key factors.
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
    "NARRATIVE_RULES",
    "validate_narrative",
    "NARRATIVE_TEMPLATES",
    "TRANSITION_PHRASES",
    "FORMATTING_RULES",
    "NARRATIVE_KNOWLEDGE",
    "get_narrative_insight",
]
