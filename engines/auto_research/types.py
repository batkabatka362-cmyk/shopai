"""Auto Research Engine — all structured types and type aliases.

Single source of truth for every data shape in the pipeline.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class ResearchGoal(TypedDict):
    """What the caller wants to research."""
    query: str
    context: str
    max_sources: int
    depth: str  # "shallow" | "standard" | "deep"


# ---------------------------------------------------------------------------
# Pipeline intermediates
# ---------------------------------------------------------------------------

class SearchQuery(TypedDict):
    """A single optimised search query produced by QueryBuilder."""
    text: str
    angle: str          # e.g. "synonym", "related_term", "question_form"
    priority: float     # 0.0–1.0


class RawSearchResult(TypedDict):
    """One result returned by a search backend."""
    title: str
    url: str
    snippet: str
    source: str
    retrieved_at: str   # ISO-8601


class ExtractedContent(TypedDict):
    """Content extracted from a single search result."""
    source_url: str
    source_title: str
    text: str
    word_count: int
    extracted_at: str


class FilteredContent(TypedDict):
    """Content that passed relevance / quality filtering."""
    source_url: str
    source_title: str
    text: str
    relevance_score: float  # 0.0–1.0
    quality_score: float    # 0.0–1.0
    word_count: int


class ResearchFeature(TypedDict):
    """A structured feature ready for analysis."""
    feature_id: str
    source_url: str
    claim: str
    evidence: str
    category: str       # "fact", "opinion", "statistic", "trend"
    strength: float     # 0.0–1.0


class AnalysisResult(TypedDict):
    """Output of the analyser step."""
    patterns: list[dict[str, Any]]
    insights: list[str]
    contradictions: list[str]
    model_used: str


class SynthesisResult(TypedDict):
    """Output of the synthesiser step."""
    insight: str
    key_findings: list[str]
    recommended_action: str
    model_used: str


class ValidationResult(TypedDict):
    """Output of validation."""
    valid: bool
    issues: list[str]


class ScoreResult(TypedDict):
    """Confidence scoring output."""
    confidence: float       # 0.0–1.0
    source_diversity: float
    evidence_strength: float
    consistency: float
    detail_breakdown: dict[str, float]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class MemoryRecord(TypedDict):
    """One record persisted by MemoryWriter."""
    record_id: str
    query: str
    insight: str
    key_findings: list[str]
    confidence: float
    sources: list[str]
    timestamp: str


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------

class ResearchData(TypedDict):
    """The ``data`` field of the engine output."""
    insight: str
    key_findings: list[str]
    recommended_action: str
    confidence: float


class ResearchMeta(TypedDict):
    """The ``meta`` field of the engine output."""
    engine: str
    sources: list[str]
    timestamp: str
    elapsed_seconds: float


class ResearchOutput(TypedDict):
    """Full engine output — the shape every caller can rely on."""
    status: str            # "success" | "fail"
    data: ResearchData | None
    meta: ResearchMeta
    error: str | None
