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
    """A rule describing an invalid variant combination to exclude."""
    # Keys are option names, values are option values to match.
    # e.g. {"size": "XXL", "color": "white"}


class ProductInput(TypedDict, total=False):
    """Product information for variant generation."""
    product_id: str
    product_code: str
    title: str
    base_price: float


class ImageInput(TypedDict, total=False):
    """Image record for variant image mapping."""
    image_id: str
    url: str
    alt_text: str
    filename: str


class InventoryRecord(TypedDict, total=False):
    """Existing inventory record to link against."""
    sku: str
    stock: int
    warehouse: str


class VariantInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    product: ProductInput
    options: list[OptionAxis]
    exclusions: list[dict[str, str]]
    images: list[ImageInput]
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

class SKURecord(TypedDict):
    """SKU and barcode for a single variant."""
    variant_index: int
    sku: str
    barcode: str


# ---------------------------------------------------------------------------
# Intermediate types — price mapping
# ---------------------------------------------------------------------------

class PriceRecord(TypedDict):
    """Price data for a single variant."""
    variant_index: int
    price: float
    adjustment: float
    compare_at_price: float


# ---------------------------------------------------------------------------
# Intermediate types — inventory linking
# ---------------------------------------------------------------------------

class InventoryLink(TypedDict):
    """Inventory link for a single variant."""
    sku: str
    stock: int
    linked: bool


# ---------------------------------------------------------------------------
# Intermediate types — image mapping
# ---------------------------------------------------------------------------

class ImageMapping(TypedDict):
    """Image mapping for a single variant."""
    variant_index: int
    image_id: str
    matched_by: str


# ---------------------------------------------------------------------------
# Intermediate types — validation
# ---------------------------------------------------------------------------

class ValidationResult(TypedDict):
    """Validation result for all variants."""
    is_valid: bool
    duplicate_skus: list[str]
    price_anomalies: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class VariantOutputData(TypedDict):
    """The 'data' block of the engine output."""
    variants: list[GeneratedVariant]
    skus: list[SKURecord]
    prices: list[PriceRecord]
    inventory: list[InventoryLink]
    image_mappings: list[ImageMapping]
    validation: ValidationResult
    total_variants: int
    excluded_count: int


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
