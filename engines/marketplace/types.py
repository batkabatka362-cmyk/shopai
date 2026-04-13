"""Marketplace Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the marketplace engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInfo(TypedDict, total=False):
    """Single product record for marketplace sync."""
    id: str
    title: str
    description: str
    price: float
    sku: str
    category: str
    images: list[str]
    attributes: dict[str, Any]


class PricingRule(TypedDict, total=False):
    """Pricing configuration for a marketplace."""
    marketplace: str
    min_margin_pct: float
    price_match: bool
    rounding_strategy: str


class InventoryRule(TypedDict, total=False):
    """Inventory allocation rule per marketplace."""
    marketplace: str
    allocation_pct: float
    buffer_units: int
    priority: int


class MarketplaceInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductInfo]
    marketplaces: list[str]
    inventory: dict[str, int]
    pricing: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — listing sync
# ---------------------------------------------------------------------------

class ListingSyncResult(TypedDict):
    """Per-platform listing sync result from listing_syncer."""
    platform: str
    listings: int
    synced: int
    errors: list[str]
    field_mapping: dict[str, str]


# ---------------------------------------------------------------------------
# Intermediate types — price harmonization
# ---------------------------------------------------------------------------

class PriceAdjustment(TypedDict):
    """Price adjustment recommendation from price_harmonizer."""
    product_id: str
    platform: str
    current_price: float
    recommended_price: float
    adjustment_reason: str
    margin_impact_pct: float


# ---------------------------------------------------------------------------
# Intermediate types — inventory allocation
# ---------------------------------------------------------------------------

class InventoryAllocation(TypedDict):
    """Per-product inventory allocation from inventory_allocator."""
    product_id: str
    total_stock: int
    allocations: dict[str, int]
    buffer_held: int


# ---------------------------------------------------------------------------
# Intermediate types — performance comparison
# ---------------------------------------------------------------------------

class PlatformPerformance(TypedDict):
    """Per-platform performance metrics from performance_comparator."""
    platform: str
    revenue: float
    orders: int
    margin: float
    conversion_rate: float
    avg_order_value: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class MarketplaceData(TypedDict):
    """The 'data' block of the engine output."""
    sync_status: list[ListingSyncResult]
    price_adjustments: list[PriceAdjustment]
    inventory_allocation: list[InventoryAllocation]
    performance: list[PlatformPerformance]


class MarketplaceMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class MarketplaceOutput(TypedDict):
    """Final output of the marketplace engine."""
    status: str
    data: MarketplaceData | None
    meta: MarketplaceMeta
    error: str | None
