"""Supplier Communication Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the supplier communication engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class SupplierRecord(TypedDict, total=False):
    """Single supplier record."""
    supplier_id: str
    name: str
    email: str
    lead_time_days: int
    min_order_value: float
    payment_terms: str
    products: list[str]


class ReorderItem(TypedDict, total=False):
    """Single reorder plan item."""
    product_id: str
    title: str
    quantity: int
    unit_cost: float
    supplier_id: str


class InventoryStatusItem(TypedDict, total=False):
    """Single inventory status item."""
    product_id: str
    current_stock: int
    days_of_stock: float
    status: str


class CommunicationRecord(TypedDict, total=False):
    """Single past communication record."""
    message_id: str
    supplier_id: str
    date: str
    subject: str
    type: str


class SupplierCommInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    suppliers: list[SupplierRecord]
    reorder_plan: list[ReorderItem]
    inventory_status: list[InventoryStatusItem]
    communication_history: list[CommunicationRecord]


# ---------------------------------------------------------------------------
# Intermediate types — purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrderItem(TypedDict):
    """Single item in a purchase order."""
    product_id: str
    title: str
    quantity: int
    unit_cost: float
    line_total: float


class PurchaseOrder(TypedDict):
    """Generated purchase order from po_generator."""
    po_id: str
    supplier_id: str
    supplier_name: str
    items: list[PurchaseOrderItem]
    total: float
    status: str
    delivery_date: str


# ---------------------------------------------------------------------------
# Intermediate types — messages
# ---------------------------------------------------------------------------

class SupplierMessage(TypedDict):
    """Generated supplier message from message_builder."""
    to: str
    supplier_id: str
    subject: str
    body: str
    type: str


# ---------------------------------------------------------------------------
# Intermediate types — tracking
# ---------------------------------------------------------------------------

class TrackingUpdate(TypedDict):
    """Tracking update from tracking_monitor."""
    po_id: str
    supplier_id: str
    status: str
    expected_delivery: str
    notes: str


# ---------------------------------------------------------------------------
# Intermediate types — negotiation
# ---------------------------------------------------------------------------

class NegotiationTip(TypedDict):
    """Negotiation tip from negotiation_helper."""
    supplier_id: str
    supplier_name: str
    tip: str
    leverage_points: list[str]
    potential_savings: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SupplierCommData(TypedDict):
    """The 'data' block of the engine output."""
    purchase_orders: list[PurchaseOrder]
    messages: list[SupplierMessage]
    tracking_updates: list[TrackingUpdate]
    negotiation_tips: list[NegotiationTip]


class SupplierCommMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SupplierCommOutput(TypedDict):
    """Final output of the supplier communication engine."""
    status: str
    data: SupplierCommData | None
    meta: SupplierCommMeta
    error: str | None
