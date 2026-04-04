"""Product Risk Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product risk engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductRiskProduct(TypedDict, total=False):
    """Single product for risk assessment."""
    id: str
    title: str
    category: str
    price: float
    margin: float
    supplier_id: str


class MarketDataItem(TypedDict, total=False):
    """Market context data."""
    category: str
    demand_trend: str
    competition_level: str
    market_volatility: float


class SupplierInfo(TypedDict, total=False):
    """Supplier information."""
    id: str
    name: str
    country: str
    lead_time_days: int
    reliability_score: float
    backup_available: bool


class ProductRiskInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductRiskProduct]
    market_data: list[MarketDataItem]
    suppliers: list[SupplierInfo]


# ---------------------------------------------------------------------------
# Intermediate types — market risk
# ---------------------------------------------------------------------------

class MarketRiskScore(TypedDict):
    """Per-product market risk from market_risk_scorer."""
    product_id: str
    demand_risk: float
    competition_risk: float
    volatility_risk: float
    market_risk_score: float
    risk_level: str


# ---------------------------------------------------------------------------
# Intermediate types — supply risk
# ---------------------------------------------------------------------------

class SupplyRiskScore(TypedDict):
    """Per-product supply risk from supply_risk_scorer."""
    product_id: str
    lead_time_risk: float
    reliability_risk: float
    concentration_risk: float
    supply_risk_score: float
    risk_level: str


# ---------------------------------------------------------------------------
# Intermediate types — legal risk
# ---------------------------------------------------------------------------

class LegalRiskScore(TypedDict):
    """Per-product legal risk from legal_risk_scorer."""
    product_id: str
    compliance_risk: float
    liability_risk: float
    regulatory_risk: float
    legal_risk_score: float
    risk_level: str


# ---------------------------------------------------------------------------
# Intermediate types — financial risk
# ---------------------------------------------------------------------------

class FinancialRiskScore(TypedDict):
    """Per-product financial risk from financial_risk_scorer."""
    product_id: str
    margin_risk: float
    price_risk: float
    capital_risk: float
    financial_risk_score: float
    risk_level: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProductRiskItem(TypedDict):
    """Single product risk assessment in output."""
    product_id: str
    market_risk: float
    supply_risk: float
    legal_risk: float
    financial_risk: float
    overall: float
    risk_level: str


class ProductRiskData(TypedDict):
    """The 'data' block of the engine output."""
    risks: list[ProductRiskItem]


class ProductRiskMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ProductRiskOutput(TypedDict):
    """Final output of the product risk engine."""
    status: str
    data: ProductRiskData | None
    meta: ProductRiskMeta
    error: str | None
