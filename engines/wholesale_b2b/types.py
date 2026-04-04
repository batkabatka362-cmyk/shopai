"""Wholesale B2B Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the wholesale B2B engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class WholesaleInputData(TypedDict, total=False):
    products: list[dict[str, Any]]
    accounts: list[dict[str, Any]]
    pricing_config: dict[str, Any]
    order: dict[str, Any]


class PricingTier(TypedDict):
    tier_name: str
    min_quantity: int
    max_quantity: int
    discount_pct: float
    unit_price: float


class AccountStatus(TypedDict):
    account_id: str
    company_name: str
    credit_limit: float
    outstanding_balance: float
    payment_terms: str
    status: str


class VolumeDiscount(TypedDict):
    product_id: str
    quantity: int
    discount_pct: float
    final_unit_price: float
    total_price: float


class ProcessedOrder(TypedDict):
    order_id: str
    account_id: str
    items: list[dict[str, Any]]
    subtotal: float
    discount_applied: float
    total: float
    payment_terms: str
    due_date: str


class WholesaleData(TypedDict):
    tiers: list[PricingTier]
    account_status: list[AccountStatus]
    volume_discounts: list[VolumeDiscount]
    processed_orders: list[ProcessedOrder]
    credit_terms: list[dict[str, Any]]


class WholesaleMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class WholesaleOutput(TypedDict):
    status: str
    data: WholesaleData | None
    meta: WholesaleMeta
    error: str | None
