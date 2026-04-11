"""Selection Reasoning Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the selection reasoning engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DecisionRecord(TypedDict, total=False):
    """Single decision record from selection_decision engine."""
    product_id: str
    title: str
    verdict: str
    confidence: float
    reasons: list[str]


class EvidenceItem(TypedDict, total=False):
    """Evidence supporting a decision."""
    product_id: str
    source: str
    metric: str
    value: Any
    interpretation: str


class ReasoningInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    decisions: list[DecisionRecord]
    evidence: list[EvidenceItem]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class NarrativeResult(TypedDict):
    """Per-product narrative from narrative_builder."""
    product_id: str
    narrative: str
    tone: str
    key_points: list[str]


class EvidenceCompilation(TypedDict):
    """Per-product evidence compilation from evidence_compiler."""
    product_id: str
    supporting_evidence: list[dict[str, Any]]
    evidence_strength: float
    gaps: list[str]


class ComparisonResult(TypedDict):
    """Per-product comparison from comparison_builder."""
    product_id: str
    compared_to: list[str]
    advantages: list[str]
    disadvantages: list[str]


class ConfidenceAssessment(TypedDict):
    """Per-product confidence from confidence_assessor."""
    product_id: str
    overall_confidence: float
    data_quality: float
    reasoning_strength: float
    caveats: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ReasoningItem(TypedDict):
    """Single product reasoning in output."""
    product_id: str
    reasoning: str
    confidence: float
    key_evidence: list[str]


class ReasoningData(TypedDict):
    """The 'data' block of the engine output."""
    narratives: list[ReasoningItem]


class ReasoningMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ReasoningOutput(TypedDict):
    """Final output of the selection reasoning engine."""
    status: str
    data: ReasoningData | None
    meta: ReasoningMeta
    error: str | None
