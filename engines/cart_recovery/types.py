"""Cart Recovery Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the cart recovery engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CartItem(TypedDict, total=False):
    """A single item in the abandoned cart."""
    title: str
    price: float
    quantity: int


class CartInfo(TypedDict, total=False):
    """The abandoned cart."""
    id: str
    customer_id: str
    items: list[CartItem]
    total: float
    abandoned_at: str  # ISO-8601


class CustomerInfo(TypedDict, total=False):
    """Customer profile data."""
    email: str
    total_orders: int
    avg_order_value: float
    last_purchase_days: int


class StoreInfo(TypedDict, total=False):
    """Store-level configuration."""
    avg_margin: float  # 0.0 – 1.0
    free_shipping_threshold: float


class CartRecoveryInput(TypedDict, total=False):
    """Top-level 'data' block of engine input."""
    cart: CartInfo
    customer: CustomerInfo
    store: StoreInfo


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class CartAnalysis(TypedDict):
    """Result from cart_analyzer."""
    total_value: float
    items_count: int
    product_categories: list[str]
    customer_type: str  # "new" | "returning" | "vip"
    hours_since_abandonment: float
    cart_value_tier: str  # "low" | "medium" | "high"


class AbandonmentClassification(TypedDict):
    """Result from abandonment_classifier."""
    reason: str  # price_shock | shipping_cost | comparison_shopping | distraction | payment_issue | just_browsing
    confidence: float
    signals: list[str]
    model_note: str


class RecoveryStrategy(TypedDict):
    """Result from recovery_strategy_selector."""
    strategy: str  # email_reminder | discount_offer | free_shipping | urgency_message | retarget_ad
    priority: str  # "low" | "medium" | "high" | "critical"
    rationale: str
    model_note: str


class Incentive(TypedDict):
    """Result from incentive_calculator."""
    type: str  # "percentage" | "free_shipping" | "bundle" | "loyalty_points" | "none"
    value: float
    max_discount_amount: float
    margin_safe: bool
    rationale: str


class RecoveryMessage(TypedDict):
    """Result from message_builder."""
    subject: str
    body: str
    cta: str
    product_reminder: str
    personalization_tokens: list[str]
    model_note: str


class TimingPlan(TypedDict):
    """Result from timing_optimizer."""
    send_at: str  # ISO-8601
    sequence: list[dict[str, Any]]  # [{delay_hours, action, message_type}]
    urgency_level: str  # "low" | "medium" | "high"
    rationale: str


class ChannelSelection(TypedDict):
    """Result from channel_selector."""
    channel: str  # "email" | "sms" | "push_notification" | "retarget_ad"
    fallback_channel: str
    rationale: str
    model_note: str


class ValueEstimate(TypedDict):
    """Result from value_estimator."""
    recovery_probability: float
    expected_revenue: float
    confidence: float
    factors: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CartRecoveryOutput(TypedDict):
    """Final output of the cart recovery engine."""
    status: str
    data: CartRecoveryData | None
    meta: CartRecoveryMeta
    error: str | None


class CartRecoveryData(TypedDict):
    """The 'data' block of the engine output."""
    strategy: str
    incentive: dict[str, Any]
    message: dict[str, Any]
    timing: dict[str, Any]
    channel: str
    recovery_probability: float
    expected_revenue: float
    confidence: float


class CartRecoveryMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
