"""Returns Management Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the returns management engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ReturnItem(TypedDict, total=False):
    """Single item within a return request."""
    product_id: str
    title: str
    quantity: int
    price: float


class ReturnRequest(TypedDict, total=False):
    """Single return request."""
    order_id: str
    items: list[ReturnItem]
    reason: str
    date: str
    customer_id: str


class ReturnPolicy(TypedDict, total=False):
    """Return policy configuration."""
    window_days: int
    restocking_fee_pct: float
    free_return_shipping: bool
    eligible_conditions: list[str]


class ReturnsInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    returns: list[ReturnRequest]
    return_policy: ReturnPolicy


# ---------------------------------------------------------------------------
# Intermediate types — return processing
# ---------------------------------------------------------------------------

class ProcessedReturn(TypedDict):
    """Per-return processing result from return_processor."""
    return_id: str
    order_id: str
    status: str
    eligible: bool
    refund_amount: float
    rejection_reason: str | None


# ---------------------------------------------------------------------------
# Intermediate types — reason analysis
# ---------------------------------------------------------------------------

class ReasonBreakdown(TypedDict):
    """Reason category breakdown from reason_analyzer."""
    category: str
    count: int
    percentage: float
    top_products: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — fraud detection
# ---------------------------------------------------------------------------

class FraudFlag(TypedDict):
    """Fraud flag from fraud_detector."""
    return_id: str
    customer_id: str
    risk_score: float
    fraud_indicators: list[str]
    recommended_action: str


# ---------------------------------------------------------------------------
# Intermediate types — cost calculation
# ---------------------------------------------------------------------------

class ReturnCostBreakdown(TypedDict):
    """Cost breakdown from cost_calculator."""
    total_refunds: float
    shipping_costs: float
    restocking_costs: float
    total_cost: float
    avg_cost_per_return: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ReturnsData(TypedDict):
    """The 'data' block of engine output."""
    processed: list[ProcessedReturn]
    reason_breakdown: list[ReasonBreakdown]
    fraud_flags: list[FraudFlag]
    total_cost: ReturnCostBreakdown
    return_rate: float


class ReturnsMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ReturnsOutput(TypedDict):
    """Final output of the returns management engine."""
    status: str
    data: ReturnsData | None
    meta: ReturnsMeta
    error: str | None
