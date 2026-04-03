"""Order Management Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the order management engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class LineItem(TypedDict, total=False):
    """Single line item in an order."""
    product_id: str
    variant_id: str
    sku: str
    title: str
    quantity: int
    price: float
    grams: int


class ShippingAddress(TypedDict, total=False):
    """Shipping address for an order."""
    first_name: str
    last_name: str
    address1: str
    address2: str
    city: str
    province: str
    zip: str
    country_code: str


class CustomerInfo(TypedDict, total=False):
    """Customer information associated with an order."""
    id: str
    email: str
    orders_count: int
    total_spent: float


class OrderInput(TypedDict, total=False):
    """Full order input record."""
    id: str
    email: str
    total_price: float
    currency: str
    line_items: list[LineItem]
    shipping_address: ShippingAddress
    billing_address: ShippingAddress
    customer: CustomerInfo


# ---------------------------------------------------------------------------
# Intermediate types — validation
# ---------------------------------------------------------------------------

class ValidationResult(TypedDict):
    """Result from order_validator."""
    status: str
    is_valid: bool
    errors: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — fraud screening
# ---------------------------------------------------------------------------

class FraudScreen(TypedDict):
    """Result from fraud_screener."""
    status: str
    risk_score: float
    risk_level: str
    recommendation: str
    flags: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — inventory check
# ---------------------------------------------------------------------------

class InventoryCheck(TypedDict):
    """Result from inventory_checker."""
    status: str
    all_in_stock: bool
    reservations: list[dict[str, Any]]
    shortages: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — fulfillment routing
# ---------------------------------------------------------------------------

class FulfillmentRoute(TypedDict):
    """Result from fulfillment_router."""
    status: str
    method: str
    warehouse_id: str
    estimated_pick_date: str


# ---------------------------------------------------------------------------
# Intermediate types — shipping
# ---------------------------------------------------------------------------

class ShippingResult(TypedDict):
    """Result from shipping_handler."""
    status: str
    carrier: str
    service: str
    estimated_cost: float
    estimated_delivery: str


# ---------------------------------------------------------------------------
# Intermediate types — tracking
# ---------------------------------------------------------------------------

class TrackingRecord(TypedDict):
    """Result from tracking_manager."""
    status: str
    tracking_id: str
    tracking_url: str
    carrier_tracking_number: str
    tracking_status: str


# ---------------------------------------------------------------------------
# Intermediate types — status update
# ---------------------------------------------------------------------------

class StatusUpdate(TypedDict):
    """Result from status_updater."""
    status: str
    current_status: str
    previous_status: str
    status_history: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Intermediate types — notification
# ---------------------------------------------------------------------------

class NotificationPayload(TypedDict):
    """Result from notification_dispatcher."""
    status: str
    notification_type: str
    subject: str
    body_preview: str
    email_sent: bool
    sms_sent: bool


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class OrderOutputData(TypedDict):
    """The 'data' block of the engine output."""
    order_id: str
    order_status: str
    validation: ValidationResult
    fraud_screen: FraudScreen
    inventory: InventoryCheck
    fulfillment: FulfillmentRoute
    shipping: ShippingResult
    tracking: TrackingRecord
    notification: NotificationPayload


class OrderMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class OrderOutput(TypedDict):
    """Final output of the order management engine."""
    status: str
    data: OrderOutputData | None
    meta: OrderMeta
    error: str | None
