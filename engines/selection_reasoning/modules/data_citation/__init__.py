"""Data Citation Module — cites specific data points supporting the decision.

Extracts key numbers from all engine results and formats them as
properly sourced citations with impact ranking and relevance filtering.
"""

from .code import cite_data
from .logic import rank_citations_by_impact, filter_relevant_citations
from .rules import CITATION_RULES, validate_citations
from .data import CITATION_TEMPLATES, DATA_SOURCE_LABELS
from .knowledge import CITATION_KNOWLEDGE, get_citation_insight

__all__ = [
    "cite_data",
    "rank_citations_by_impact",
    "filter_relevant_citations",
    "CITATION_RULES",
    "validate_citations",
    "CITATION_TEMPLATES",
    "DATA_SOURCE_LABELS",
    "CITATION_KNOWLEDGE",
    "get_citation_insight",
]
