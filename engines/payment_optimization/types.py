"""Payment Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the payment optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class Transaction(TypedDict, total=False):
    """Single transaction record."""
    id: str
    amount: float
    payment_method: str
    processor: str
    fee: float
    status: str
    is_fraud: bool


class PaymentMethod(TypedDict, total=False):
    """Payment method info."""
    name: str
    type: str
    base_fee: float
    pct_fee: float
    avg_decline_rate: float


class FeeSchedule(TypedDict, total=False):
    """Fee schedule for a processor."""
    processor: str
    base_fee: float
    pct_fee: float
    chargeback_fee: float


class PaymentInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    transactions: list[Transaction]
    payment_methods: list[PaymentMethod]
    fees: list[FeeSchedule]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class FeeAnalysisItem(TypedDict):
    """Per-method fee analysis from fee_analyzer."""
    payment_method: str
    total_fees: float
    avg_fee_pct: float
    transaction_count: int
    total_volume: float


class RoutingRecommendation(TypedDict):
    """Routing recommendation from routing_optimizer."""
    payment_method: str
    recommended_processor: str
    current_fee_pct: float
    optimized_fee_pct: float
    monthly_savings: float


class CheckoutOptimization(TypedDict):
    """Checkout optimization from checkout_optimizer."""
    recommendation: str
    expected_conversion_lift: float
    priority: str


class FraudCostItem(TypedDict):
    """Fraud cost tracking from fraud_cost_tracker."""
    period: str
    fraud_losses: float
    chargeback_fees: float
    prevention_cost: float
    net_fraud_cost: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class PaymentData(TypedDict):
    """The 'data' block of the engine output."""
    fee_analysis: list[FeeAnalysisItem]
    routing_recommendations: list[RoutingRecommendation]
    total_savings: float


class PaymentMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class PaymentOutput(TypedDict):
    """Final output of the payment optimization engine."""
    status: str
    data: PaymentData | None
    meta: PaymentMeta
    error: str | None
