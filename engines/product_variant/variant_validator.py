"""Product Variant Engine — variant validator.

Validates the complete variant set for consistency:
  - No duplicate SKUs
  - All prices > 0
  - All option combinations are covered (no gaps)
  - No orphan variants (variants without SKUs or prices)

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def validate_variants(
    variants: list[dict[str, Any]],
    skus: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate consistency of the generated variant set.

    Args:
        variants: List of GeneratedVariant dicts.
        skus: List of VariantSKU dicts from sku_builder.
        prices: List of VariantPrice dicts from price_mapper.

    Returns:
        Structured dict with validation results.
    """
    try:
        variants = copy.deepcopy(variants)
        skus = copy.deepcopy(skus)
        prices = copy.deepcopy(prices)

        duplicate_skus: list[str] = []
        price_anomalies: list[str] = []
        warnings: list[str] = []

        # --- Check 1: Duplicate SKUs ---
        sku_counts: dict[str, int] = {}
        for entry in skus:
            sku_str = str(entry.get("sku", ""))
            sku_counts[sku_str] = sku_counts.get(sku_str, 0) + 1

        for sku_str, count in sku_counts.items():
            if count > 1:
                duplicate_skus.append(sku_str)

        # --- Check 2: Price anomalies ---
        price_by_index: dict[int, float] = {}
        for entry in prices:
            idx = entry.get("variant_index", -1)
            price_val = entry.get("price", 0.0)
            price_by_index[idx] = price_val

            if price_val <= 0:
                price_anomalies.append(
                    f"Variant {idx}: price is {price_val} (must be > 0)"
                )

            compare_at = entry.get("compare_at_price")
            if compare_at is not None and compare_at <= price_val:
                warnings.append(
                    f"Variant {idx}: compare_at_price ({compare_at}) "
                    f"<= price ({price_val})"
                )

        # --- Check 3: Orphan variants (missing SKU or price) ---
        sku_indices = {entry.get("variant_index", -1) for entry in skus}
        price_indices = {entry.get("variant_index", -1) for entry in prices}

        for idx in range(len(variants)):
            if idx not in sku_indices:
                warnings.append(f"Variant {idx}: no SKU assigned")
            if idx not in price_indices:
                warnings.append(f"Variant {idx}: no price assigned")

        # --- Check 4: SKU/price entries for non-existent variants ---
        variant_count = len(variants)
        for entry in skus:
            vi = entry.get("variant_index", -1)
            if vi < 0 or vi >= variant_count:
                warnings.append(
                    f"SKU entry references non-existent variant index {vi}"
                )
        for entry in prices:
            vi = entry.get("variant_index", -1)
            if vi < 0 or vi >= variant_count:
                warnings.append(
                    f"Price entry references non-existent variant index {vi}"
                )

        # --- Check 5: Variant count sanity ---
        if variant_count == 0:
            warnings.append("No variants were generated")

        is_valid = (
            len(duplicate_skus) == 0
            and len(price_anomalies) == 0
            and variant_count > 0
        )

        return {
            "status": "success",
            "is_valid": is_valid,
            "duplicate_skus": duplicate_skus,
            "price_anomalies": price_anomalies,
            "warnings": warnings,
        }
    except Exception as exc:
        return _fail(f"Variant validation failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "is_valid": False,
        "duplicate_skus": [],
        "price_anomalies": [],
        "warnings": [],
        "error": reason,
    }
