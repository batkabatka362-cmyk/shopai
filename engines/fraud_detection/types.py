"""Fraud Detection Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the fraud detection engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class OrderAddress(TypedDict, total=False):
    """Shipping or billing address."""
    line1: str
    line2: str
    city: str
    state: str
    zip: str
    country: str


class CustomerInfo(TypedDict, total=False):
    """Customer data embedded in the order."""
    id: str
    email: str
    phone: str
    account_age_days: int
    order_count: int
    avg_order_value: float


class OrderData(TypedDict, total=False):
    """Single order record."""
    id: str
    email: str
    ip_address: str
    total_price: float
    currency: str
    item_count: int
    has_gift_card: bool
    shipping_address: OrderAddress
    billing_address: OrderAddress
    customer: CustomerInfo
    created_at: str


class DeviceData(TypedDict, total=False):
    """Device fingerprint data."""
    user_agent: str
    screen_resolution: str
    timezone: str
    language: str
    cookies_enabled: bool
    javascript_enabled: bool


class FraudInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    order: OrderData
    device: DeviceData


class FraudInput(TypedDict, total=False):
    """Full engine input payload."""
    status: str
    data: FraudInputData
    meta: dict[str, Any]
    error: str | None


# ---------------------------------------------------------------------------
# Intermediate types — risk signals
# ---------------------------------------------------------------------------

class RiskSignal(TypedDict, total=False):
    """Generic risk signal returned by any scoring module."""
    status: str
    score: float
    error: str | None


class VelocityResult(TypedDict):
    """Result from velocity_checker."""
    status: str
    score: float
    orders_1h: int
    orders_24h: int
    orders_7d: int
    flag: str | None


class AddressCheck(TypedDict):
    """Result from address_verifier."""
    status: str
    score: float
    billing_shipping_match: bool
    is_po_box: bool
    is_freight_forwarder: bool
    country_risk: str


class PatternMatch(TypedDict):
    """Result from pattern_detector."""
    status: str
    score: float
    detected_patterns: list[str]
    model_note: str


class BlacklistResult(TypedDict):
    """Result from blacklist_checker."""
    status: str
    score: float
    email_listed: bool
    ip_listed: bool
    phone_listed: bool
    address_listed: bool


class DeviceFingerprint(TypedDict):
    """Result from device_fingerprinter."""
    status: str
    score: float
    is_bot: bool
    timezone_consistent: bool
    fingerprint_hash: str


class FraudVerdict(TypedDict):
    """Result from decision_maker."""
    status: str
    verdict: str
    risk_score: float
    risk_level: str
    confidence: float


class FraudAlert(TypedDict, total=False):
    """Alert generated for high-risk orders."""
    alert_id: str
    order_id: str
    risk_level: str
    risk_score: float
    verdict: str
    top_signals: list[str]
    recommended_actions: list[str]
    timestamp: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class FraudOutputData(TypedDict):
    """The 'data' block of the engine output."""
    order_id: str
    verdict: str
    risk_score: float
    risk_level: str
    confidence: float
    signals: dict[str, Any]
    recommended_actions: list[str]
    alert: FraudAlert | None


class FraudMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class FraudOutput(TypedDict):
    """Final output of the fraud detection engine."""
    status: str
    data: FraudOutputData | None
    meta: FraudMeta
    error: str | None
