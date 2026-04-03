"""Affiliate Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the affiliate engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class AffiliateProduct(TypedDict, total=False):
    """Product available for affiliate program."""
    id: str
    title: str
    price: float
    category: str
    margin_pct: float


class SaleRecord(TypedDict, total=False):
    """Single affiliate sale record."""
    sale_id: str
    partner_id: str
    product_id: str
    amount: float
    date: str


class AffiliatePartner(TypedDict, total=False):
    """Affiliate partner info."""
    id: str
    name: str
    channel: str
    join_date: str
    total_sales: float
    total_referrals: int


class CommissionRule(TypedDict, total=False):
    """Commission rule configuration."""
    tier: str
    min_sales: float
    commission_pct: float
    bonus: float


class AffiliateInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[AffiliateProduct]
    sales_data: list[SaleRecord]
    partners: list[AffiliatePartner]
    commission_rules: list[CommissionRule]


# ---------------------------------------------------------------------------
# Intermediate types — program design
# ---------------------------------------------------------------------------

class CommissionTier(TypedDict):
    """Commission tier from program_designer."""
    tier_name: str
    min_sales: float
    commission_pct: float
    bonus: float


class ProgramDesign(TypedDict):
    """Program design from program_designer."""
    commission_tiers: list[CommissionTier]
    cookie_duration_days: int
    rules: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — partner evaluation
# ---------------------------------------------------------------------------

class PartnerScore(TypedDict):
    """Partner score from partner_evaluator."""
    partner_id: str
    name: str
    score: float
    conversion_rate: float
    avg_order_value: float
    quality_tier: str


# ---------------------------------------------------------------------------
# Intermediate types — commission calculation
# ---------------------------------------------------------------------------

class CommissionDue(TypedDict):
    """Commission due from commission_calculator."""
    partner_id: str
    name: str
    period_sales: float
    commission_rate: float
    commission_amount: float
    tier: str


# ---------------------------------------------------------------------------
# Intermediate types — performance tracking
# ---------------------------------------------------------------------------

class PerformanceRecord(TypedDict):
    """Performance record from performance_tracker."""
    partner_id: str
    name: str
    total_sales: float
    total_referrals: int
    conversion_rate: float
    revenue_trend: str
    rank: int


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProgramHealth(TypedDict):
    """Overall program health metrics."""
    total_partners: int
    active_partners: int
    total_commission_paid: float
    avg_partner_revenue: float
    program_roi: float


class AffiliateData(TypedDict):
    """The 'data' block of engine output."""
    program: ProgramDesign
    partner_scores: list[PartnerScore]
    commissions_due: list[CommissionDue]
    top_performers: list[PerformanceRecord]
    program_health: ProgramHealth


class AffiliateMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AffiliateOutput(TypedDict):
    """Final output of the affiliate engine."""
    status: str
    data: AffiliateData | None
    meta: AffiliateMeta
    error: str | None
