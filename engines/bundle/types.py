"""Bundle Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the bundle engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BundleProduct(TypedDict, total=False):
    """Product available for bundling."""
    id: str
    title: str
    price: float
    cost: float
    category: str
    daily_sales: float


class OrderRecord(TypedDict, total=False):
    """Single order record for affinity analysis."""
    order_id: str
    product_ids: list[str]
    total: float
    date: str


class PricingData(TypedDict, total=False):
    """Pricing constraints and data."""
    min_discount_pct: float
    max_discount_pct: float
    target_margin_pct: float


class BundleConstraints(TypedDict, total=False):
    """Constraints for bundle generation."""
    min_products: int
    max_products: int
    max_bundles: int


class BundleInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[BundleProduct]
    orders: list[OrderRecord]
    pricing_data: PricingData
    constraints: BundleConstraints


# ---------------------------------------------------------------------------
# Intermediate types — affinity analysis
# ---------------------------------------------------------------------------

class ProductAffinity(TypedDict):
    """Product pair affinity from affinity_analyzer."""
    product_a: str
    product_b: str
    co_purchase_count: int
    affinity_score: float
    lift: float


# ---------------------------------------------------------------------------
# Intermediate types — bundle generation
# ---------------------------------------------------------------------------

class GeneratedBundle(TypedDict):
    """Bundle candidate from bundle_generator."""
    bundle_id: str
    product_ids: list[str]
    product_titles: list[str]
    combined_price: float
    affinity_score: float


# ---------------------------------------------------------------------------
# Intermediate types — price optimization
# ---------------------------------------------------------------------------

class OptimizedBundle(TypedDict):
    """Price-optimized bundle from price_optimizer."""
    bundle_id: str
    product_ids: list[str]
    product_titles: list[str]
    original_price: float
    bundle_price: float
    savings_pct: float
    estimated_uplift: float
    margin: float


# ---------------------------------------------------------------------------
# Intermediate types — cannibalization check
# ---------------------------------------------------------------------------

class CannibalizationResult(TypedDict):
    """Cannibalization check from cannibalization_checker."""
    bundle_id: str
    cannibalization_risk: float
    affected_products: list[str]
    net_revenue_impact: float
    recommendation: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BundleOutputItem(TypedDict):
    """Single bundle in engine output."""
    products: list[str]
    bundle_price: float
    savings_pct: float
    estimated_uplift: float
    margin: float


class BundleData(TypedDict):
    """The 'data' block of engine output."""
    bundles: list[BundleOutputItem]
    best_bundle: BundleOutputItem | None
    cannibalization_risk: list[CannibalizationResult]


class BundleMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BundleOutput(TypedDict):
    """Final output of the bundle engine."""
    status: str
    data: BundleData | None
    meta: BundleMeta
    error: str | None
