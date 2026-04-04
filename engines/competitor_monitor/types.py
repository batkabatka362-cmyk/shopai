"""Competitor Monitor Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competitor monitor engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CompetitorRecord(TypedDict, total=False):
    """Single competitor record."""
    name: str
    url: str
    products: list[dict[str, Any]]


class CompetitorProduct(TypedDict, total=False):
    """Single competitor product."""
    product_id: str
    title: str
    price: float
    category: str


class OurProduct(TypedDict, total=False):
    """Single product from our catalog."""
    product_id: str
    title: str
    price: float
    cost: float
    category: str


class AlertThresholds(TypedDict, total=False):
    """Alert threshold configuration."""
    price_change_pct: float
    undercut_pct: float
    new_product_alert: bool


class CompetitorMonitorInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    competitors: list[CompetitorRecord]
    our_products: list[OurProduct]
    alert_thresholds: AlertThresholds


# ---------------------------------------------------------------------------
# Intermediate types — price watching
# ---------------------------------------------------------------------------

class PriceChange(TypedDict):
    """Price change detected by price_watcher."""
    competitor: str
    product_id: str
    product_title: str
    old_price: float
    new_price: float
    change_pct: float
    direction: str


# ---------------------------------------------------------------------------
# Intermediate types — product scanning
# ---------------------------------------------------------------------------

class NewCompetitorProduct(TypedDict):
    """New competitor product detected by product_scanner."""
    competitor: str
    product_id: str
    product_title: str
    price: float
    category: str
    threat_level: str


# ---------------------------------------------------------------------------
# Intermediate types — alerts
# ---------------------------------------------------------------------------

class CompetitorAlert(TypedDict):
    """Alert from alert_generator."""
    alert_type: str
    severity: str
    competitor: str
    message: str
    recommended_action: str


# ---------------------------------------------------------------------------
# Intermediate types — strategy
# ---------------------------------------------------------------------------

class StrategyResponse(TypedDict):
    """Strategic response from strategy_advisor."""
    competitor: str
    situation: str
    recommended_response: str
    expected_impact: str
    urgency: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CompetitorMonitorData(TypedDict):
    """The 'data' block of the engine output."""
    price_changes: list[PriceChange]
    new_products: list[NewCompetitorProduct]
    alerts: list[CompetitorAlert]
    recommended_responses: list[StrategyResponse]


class CompetitorMonitorMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CompetitorMonitorOutput(TypedDict):
    """Final output of the competitor monitor engine."""
    status: str
    data: CompetitorMonitorData | None
    meta: CompetitorMonitorMeta
    error: str | None
