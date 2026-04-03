"""Product Filter Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product filter engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductCandidate(TypedDict, total=False):
    """Single product candidate to filter."""
    id: str
    title: str
    margin_pct: float
    unit_cost: float
    sale_price: float
    weight_kg: float
    category: str
    brand: str
    origin_country: str
    restricted: bool


class FilterCriteria(TypedDict, total=False):
    """Criteria for filtering products."""
    min_margin_pct: float
    max_weight_kg: float
    blocked_categories: list[str]
    blocked_brands: list[str]
    allowed_countries: list[str]
    brand_profile: dict[str, Any]


class FilterInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductCandidate]
    criteria: FilterCriteria


# ---------------------------------------------------------------------------
# Intermediate types — margin filter
# ---------------------------------------------------------------------------

class MarginFilterResult(TypedDict):
    """Result from margin_filter module."""
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    rejection_reasons: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — legal filter
# ---------------------------------------------------------------------------

class LegalFilterResult(TypedDict):
    """Result from legal_filter module."""
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    compliance_notes: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — shipping filter
# ---------------------------------------------------------------------------

class ShippingFilterResult(TypedDict):
    """Result from shipping_filter module."""
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    feasibility_notes: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — brand filter
# ---------------------------------------------------------------------------

class BrandFilterResult(TypedDict):
    """Result from brand_filter module."""
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    fit_scores: dict[str, float]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class FilterSummary(TypedDict):
    """Summary of filter results."""
    total_input: int
    total_passed: int
    total_rejected: int
    margin_rejected: int
    legal_rejected: int
    shipping_rejected: int
    brand_rejected: int


class FilterOutput(TypedDict):
    """Final output of the product filter engine."""
    status: str
    data: FilterOutputData | None
    meta: FilterMeta
    error: str | None


class FilterOutputData(TypedDict):
    """The 'data' block of the engine output."""
    accepted_products: list[dict[str, Any]]
    rejected_products: list[dict[str, Any]]
    filter_summary: FilterSummary


class FilterMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
