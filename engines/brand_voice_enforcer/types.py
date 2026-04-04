"""Brand Voice Enforcer Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the brand voice enforcer engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ContentItem(TypedDict, total=False):
    """Single content item to analyze."""
    type: str
    text: str


class BrandVoiceSpec(TypedDict, total=False):
    """Brand voice specification."""
    tone: str
    vocabulary: list[str]
    dos: list[str]
    donts: list[str]


class VoiceEnforcerInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    content: list[ContentItem]
    brand_voice: BrandVoiceSpec


# ---------------------------------------------------------------------------
# Intermediate types — content analysis
# ---------------------------------------------------------------------------

class ContentAnalysis(TypedDict):
    """Per-content analysis from content_analyzer."""
    content_idx: int
    word_count: int
    sentence_count: int
    avg_sentence_length: float
    formality_score: float
    vocabulary_alignment: float


# ---------------------------------------------------------------------------
# Intermediate types — tone check
# ---------------------------------------------------------------------------

class ToneCheckResult(TypedDict):
    """Per-content tone check from tone_checker."""
    content_idx: int
    detected_tone: str
    tone_match_score: float
    tone_issues: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — vocabulary filter
# ---------------------------------------------------------------------------

class VocabularyFilterResult(TypedDict):
    """Per-content vocabulary filter from vocabulary_filter."""
    content_idx: int
    off_brand_words: list[str]
    suggested_replacements: dict[str, str]
    on_brand_word_count: int


# ---------------------------------------------------------------------------
# Intermediate types — consistency score
# ---------------------------------------------------------------------------

class ConsistencyResult(TypedDict):
    """Per-content consistency score from consistency_scorer."""
    content_idx: int
    consistency_score: int
    issues: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ContentScore(TypedDict):
    """Per-content score in engine output."""
    content_idx: int
    consistency_score: int
    issues: list[str]


class VoiceEnforcerData(TypedDict):
    """The 'data' block of the engine output."""
    scores: list[ContentScore]
    overall_score: int
    corrections: list[dict[str, Any]]
    recommendations: list[str]


class VoiceEnforcerMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class VoiceEnforcerOutput(TypedDict):
    """Final output of the brand voice enforcer engine."""
    status: str
    data: VoiceEnforcerData | None
    meta: VoiceEnforcerMeta
    error: str | None
