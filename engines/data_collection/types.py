"""Data Collection Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the data collection engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DataCollectionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    sources: list[str]
    date_range: dict[str, str]
    filters: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — source resolution
# ---------------------------------------------------------------------------

class ResolvedSource(TypedDict):
    """A resolved API source ready for fetching."""
    name: str
    endpoint: str
    auth_type: str
    rate_limit: int
    priority: int


# ---------------------------------------------------------------------------
# Intermediate types — fetched data
# ---------------------------------------------------------------------------

class FetchedSourceData(TypedDict):
    """Raw data fetched from a single source."""
    source: str
    records: list[dict[str, Any]]
    count: int
    fetch_time_ms: float
    status: str


# ---------------------------------------------------------------------------
# Intermediate types — normalized data
# ---------------------------------------------------------------------------

class NormalizedRecord(TypedDict):
    """A single normalized record in common format."""
    id: str
    source: str
    entity_type: str
    data: dict[str, Any]
    timestamp: str


# ---------------------------------------------------------------------------
# Intermediate types — freshness check
# ---------------------------------------------------------------------------

class FreshnessReport(TypedDict):
    """Freshness assessment for a data source."""
    source: str
    latest_record_ts: str
    age_hours: float
    is_stale: bool
    freshness_score: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CollectedSourceSummary(TypedDict):
    """Summary for a single collected source."""
    records: list[dict[str, Any]]
    count: int


class DataCollectionData(TypedDict):
    """The 'data' block of the engine output."""
    collected: dict[str, CollectedSourceSummary]
    total_records: int
    freshness: dict[str, FreshnessReport]


class DataCollectionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DataCollectionOutput(TypedDict):
    """Final output of the data collection engine."""
    status: str
    data: DataCollectionData | None
    meta: DataCollectionMeta
    error: str | None
