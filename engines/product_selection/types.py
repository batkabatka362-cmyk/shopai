"""Product Selection Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product selection engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class MarketDataItem(TypedDict, total=False):
    """Single market data item."""
    id: str
    name: str
    category: str
    demand_score: float
    price: float
    cost: float


class SupplierRecord(TypedDict, total=False):
    """Supplier information record."""
    id: str
    name: str
    reliability: float
    lead_time_days: int
    product_ids: list[str]


class SelectionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    market_data: list[MarketDataItem]
    criteria: dict[str, Any]
    suppliers: list[SupplierRecord]


# ---------------------------------------------------------------------------
# Intermediate types — candidate generator
# ---------------------------------------------------------------------------

class GeneratedCandidate(TypedDict):
    """Candidate from generator."""
    id: str
    name: str
    category: str
    demand_score: float
    price: float
    cost: float
    margin: float


# ---------------------------------------------------------------------------
# Intermediate types — criteria matcher
# ---------------------------------------------------------------------------

class MatchedCandidate(TypedDict):
    """Candidate after criteria matching."""
    id: str
    name: str
    criteria_pass: bool
    criteria_reasons: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — initial scorer
# ---------------------------------------------------------------------------

class ScoredCandidate(TypedDict):
    """Candidate with initial score."""
    id: str
    name: str
    initial_score: float
    criteria_pass: bool
    supplier_available: bool


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SelectionOutputData(TypedDict):
    """The 'data' block of engine output."""
    candidates: list[dict[str, Any]]
    shortlist: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


class SelectionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SelectionOutput(TypedDict):
    """Final output of the product selection engine."""
    status: str
    data: SelectionOutputData | None
    meta: SelectionMeta
    error: str | None
