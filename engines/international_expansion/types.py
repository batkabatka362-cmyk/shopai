"""International Expansion Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the international expansion engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ExpansionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[dict[str, Any]]
    target_markets: list[str]
    current_currency: str


# ---------------------------------------------------------------------------
# Intermediate types — market evaluation
# ---------------------------------------------------------------------------

class MarketScore(TypedDict):
    """Per-market evaluation from market_evaluator."""
    market: str
    gdp_score: float
    ecommerce_penetration: float
    ease_of_entry: float
    overall_score: float
    recommendation: str


# ---------------------------------------------------------------------------
# Intermediate types — currency pricing
# ---------------------------------------------------------------------------

class CurrencyPricing(TypedDict):
    """Per-market currency pricing from currency_manager."""
    market: str
    local_currency: str
    exchange_rate: float
    converted_prices: list[dict[str, Any]]
    rounding_strategy: str


# ---------------------------------------------------------------------------
# Intermediate types — localization
# ---------------------------------------------------------------------------

class LocalizationGap(TypedDict):
    """Localization readiness gap from localization_checker."""
    market: str
    language: str
    translation_ready: bool
    missing_fields: list[str]
    cultural_notes: list[str]
    readiness_pct: float


# ---------------------------------------------------------------------------
# Intermediate types — shipping
# ---------------------------------------------------------------------------

class ShippingPlan(TypedDict):
    """Per-market shipping plan from shipping_planner."""
    market: str
    shipping_zones: list[str]
    estimated_cost_per_unit: float
    estimated_transit_days: int
    customs_notes: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ExpansionData(TypedDict):
    """The 'data' block of the engine output."""
    market_scores: list[MarketScore]
    currency_pricing: list[CurrencyPricing]
    localization_gaps: list[LocalizationGap]
    shipping_plans: list[ShippingPlan]
    recommended_markets: list[str]


class ExpansionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ExpansionOutput(TypedDict):
    """Final output of the international expansion engine."""
    status: str
    data: ExpansionData | None
    meta: ExpansionMeta
    error: str | None
