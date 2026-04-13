"""Data Enrichment Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the data enrichment engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DataEnrichmentInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    raw_data: list[dict[str, Any]]
    enrichment_level: str


# ---------------------------------------------------------------------------
# Intermediate types — stat calculation
# ---------------------------------------------------------------------------

class ComputedStat(TypedDict):
    """A computed statistic for a data record."""
    record_id: str
    stats: dict[str, float]
    stat_type: str


# ---------------------------------------------------------------------------
# Intermediate types — features
# ---------------------------------------------------------------------------

class DerivedFeature(TypedDict):
    """A derived feature built from raw data."""
    feature_name: str
    feature_value: Any
    source_fields: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# Intermediate types — quality scoring
# ---------------------------------------------------------------------------

class QualityReport(TypedDict):
    """Quality assessment for a data record."""
    record_id: str
    completeness: float
    accuracy: float
    consistency: float
    overall_score: float


# ---------------------------------------------------------------------------
# Intermediate types — gap detection
# ---------------------------------------------------------------------------

class DataGap(TypedDict):
    """A detected gap in the data."""
    field: str
    gap_type: str
    affected_records: int
    severity: str
    suggestion: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class DataEnrichmentData(TypedDict):
    """The 'data' block of the engine output."""
    enriched_data: list[dict[str, Any]]
    features: list[DerivedFeature]
    quality_score: float
    gaps: list[DataGap]


class DataEnrichmentMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DataEnrichmentOutput(TypedDict):
    """Final output of the data enrichment engine."""
    status: str
    data: DataEnrichmentData | None
    meta: DataEnrichmentMeta
    error: str | None
