"""Cross-Sell Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the cross-sell engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CartProduct(TypedDict, total=False):
    """A single product in the current cart."""
    product_id: str
    title: str
    category: str
    price: float


class PastPurchase(TypedDict, total=False):
    """A historical purchase record."""
    product_id: str
    category: str


class CustomerInfo(TypedDict, total=False):
    """Customer profile for cross-sell targeting."""
    past_purchases: list[PastPurchase]
    preferences: list[str]


class CatalogProduct(TypedDict, total=False):
    """A product from the store catalog."""
    product_id: str
    title: str
    category: str
    price: float
    margin: float


class CrossSellInput(TypedDict, total=False):
    """Top-level 'data' block of engine input."""
    current_cart: list[CartProduct]
    customer: CustomerInfo
    catalog: list[CatalogProduct]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class PurchaseAnalysis(TypedDict):
    """Result from purchase_analyzer."""
    frequent_combos: list[list[str]]  # lists of product_id pairs seen together
    category_preferences: dict[str, float]  # category -> affinity score
    price_range: dict[str, float]  # min, max, avg
    cart_categories: list[str]
    cart_product_ids: list[str]
    total_cart_value: float
    timing_signals: dict[str, Any]


class AssociationRule(TypedDict):
    """A single co-purchase association rule."""
    antecedent: str  # product_id or category
    consequent: str  # product_id or category
    support: float  # proportion of transactions containing both
    confidence: float  # P(consequent | antecedent)
    lift: float  # confidence / P(consequent)
    model_note: str


class AssociationResult(TypedDict):
    """Result from association_finder."""
    rules: list[AssociationRule]
    top_associated_products: list[str]
    model_note: str


class ComplementMatch(TypedDict):
    """A single complement match from complement_matcher."""
    product_id: str
    title: str
    category: str
    price: float
    margin: float
    complement_type: str  # "accessory" | "care_product" | "companion" | "upgrade"
    matched_cart_item: str  # product_id of the cart item it complements
    rule_reason: str


class AffinityScore(TypedDict):
    """Scored product from affinity_scorer."""
    product_id: str
    title: str
    category: str
    price: float
    margin: float
    co_purchase_score: float
    category_complement_score: float
    price_compatibility_score: float
    review_correlation_score: float
    total_affinity: float
    complement_type: str
    matched_cart_item: str


class Bundle(TypedDict):
    """A cross-sell bundle from bundle_builder."""
    bundle_id: str
    products: list[dict[str, Any]]  # [{product_id, title, price}]
    bundle_price: float
    discount_percent: float
    projected_margin: float
    reason: str
    model_note: str


class RevenueEstimate(TypedDict):
    """Revenue impact estimate from revenue_estimator."""
    product_id: str
    conversion_probability: float
    expected_revenue: float
    aov_increase: float
    margin_on_item: float
    factors: list[str]


class RankedRecommendation(TypedDict):
    """A single ranked recommendation from recommendation_ranker."""
    product_id: str
    title: str
    reason: str
    score: float
    expected_revenue: float
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CrossSellOutput(TypedDict):
    """Final output of the cross-sell engine."""
    status: str
    data: CrossSellData | None
    meta: CrossSellMeta
    error: str | None


class CrossSellData(TypedDict):
    """The 'data' block of the engine output."""
    recommendations: list[RankedRecommendation]
    bundles: list[Bundle]
    estimated_aov_increase: float
    confidence: float


class CrossSellMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
