"""Checkout Optimizer Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the checkout optimizer engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CheckoutAnalytics(TypedDict, total=False):
    """Analytics data for checkout optimization."""
    cart_abandonment_rate: float
    checkout_steps: list[dict[str, Any]]


class CheckoutOptimizerInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    checkout_config: dict[str, Any]
    analytics: CheckoutAnalytics
    payment_methods: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — friction analysis
# ---------------------------------------------------------------------------

class FrictionPoint(TypedDict):
    """Single friction point from friction_analyzer."""
    step: str
    issue: str
    impact: str
    severity: str
    drop_off_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — form optimization
# ---------------------------------------------------------------------------

class FormOptimization(TypedDict):
    """Single form optimization from form_optimizer."""
    field: str
    current_issue: str
    recommendation: str
    expected_lift: float


# ---------------------------------------------------------------------------
# Intermediate types — trust signals
# ---------------------------------------------------------------------------

class TrustSignal(TypedDict):
    """Single trust signal from trust_builder."""
    type: str
    placement: str
    content: str
    priority: int


# ---------------------------------------------------------------------------
# Intermediate types — payment optimization
# ---------------------------------------------------------------------------

class PaymentRecommendation(TypedDict):
    """Single payment recommendation from payment_optimizer."""
    method: str
    recommendation: str
    expected_adoption: float
    priority: str


# ---------------------------------------------------------------------------
# Engine output — optimization item
# ---------------------------------------------------------------------------

class OptimizationItem(TypedDict):
    """Single optimization recommendation in output."""
    type: str
    recommendation: str
    expected_lift: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CheckoutOptimizerData(TypedDict):
    """The 'data' block of the engine output."""
    friction_points: list[FrictionPoint]
    optimizations: list[OptimizationItem]
    trust_signals: list[TrustSignal]
    payment_recommendations: list[PaymentRecommendation]


class CheckoutOptimizerMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CheckoutOptimizerOutput(TypedDict):
    """Final output of the checkout optimizer engine."""
    status: str
    data: CheckoutOptimizerData | None
    meta: CheckoutOptimizerMeta
    error: str | None
