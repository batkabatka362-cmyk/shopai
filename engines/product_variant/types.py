"""Product Variant Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product variant engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class OptionAxis(TypedDict, total=False):
    """A single option axis (e.g. size, color, material)."""
    name: str
    values: list[str]
    price_adjustments: dict[str, float]


class ExclusionRule(TypedDict, total=False):
    """A rule to exclude specific variant combinations."""
    # Keys are option names, values are option values to exclude together.
    # e.g. {"size": "XXL", "color": "white"} excludes XXL-white.
    conditions: dict[str, str]


class ProductInput(TypedDict, total=False):
    """Product information for variant generation."""
    product_id: str
    product_code: str
    title: str
    base_price: float
    compare_at_price: float
    country_code: str


class ImageRecord(TypedDict, total=False):
    """An image available for mapping to variants."""
    image_id: str
    src: str
    alt: str
    filename: str


class InventoryRecord(TypedDict, total=False):
    """An existing inventory record that can be linked to a variant."""
    sku: str
    stock: int
    warehouse: str


class VariantInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: ProductInput
    options: list[OptionAxis]
    exclusions: list[ExclusionRule]
    images: list[ImageRecord]
    inventory_data: list[InventoryRecord]


# ---------------------------------------------------------------------------
# Intermediate types — variant generation
# ---------------------------------------------------------------------------

class GeneratedVariant(TypedDict):
    """A single generated variant combination."""
    options: dict[str, str]
    position: int


# ---------------------------------------------------------------------------
# Intermediate types — SKU building
# ---------------------------------------------------------------------------

class VariantSKU(TypedDict):
    """SKU and barcode for a variant."""
    variant_index: int
    sku: str
    barcode: str


# ---------------------------------------------------------------------------
# Intermediate types — price mapping
# ---------------------------------------------------------------------------

class VariantPrice(TypedDict):
    """Price info for a variant."""
    variant_index: int
    price: float
    adjustment: float
    compare_at_price: float | None


# ---------------------------------------------------------------------------
# Intermediate types — inventory linking
# ---------------------------------------------------------------------------

class VariantInventory(TypedDict):
    """Inventory link for a variant."""
    sku: str
    stock: int
    linked: bool


# ---------------------------------------------------------------------------
# Intermediate types — image mapping
# ---------------------------------------------------------------------------

class ImageMapping(TypedDict):
    """Image-to-variant mapping."""
    variant_index: int
    image_id: str
    matched_by: str


# ---------------------------------------------------------------------------
# Intermediate types — validation
# ---------------------------------------------------------------------------

class ValidationResult(TypedDict):
    """Validation result for the variant set."""
    is_valid: bool
    duplicate_skus: list[str]
    price_anomalies: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class VariantOutputData(TypedDict):
    """The 'data' block of engine output."""
    product_id: str
    product_code: str
    total_variants: int
    excluded_count: int
    variants: list[dict]
    validation: ValidationResult
    linked_inventory: int
    unlinked_inventory: int


class VariantMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class VariantOutput(TypedDict):
    """Final output of the product variant engine."""
    status: str
    data: VariantOutputData | None
    meta: VariantMeta
    error: str | None
