"""Product Variant Engine — variant validator.

Validates consistency across variants, SKUs, and prices:
- No duplicate SKUs
- All prices > 0
- All option combos are covered (no orphans)
- No orphan variants (variants without SKU or price)

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
    """Validate variant data for consistency.

    Args:
        variants: List of variant dicts from variant_generator.
        skus: List of SKU dicts from sku_builder.
        prices: List of price dicts from price_mapper.

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
        sku_strings: list[str] = []
        seen_skus: set[str] = set()
        for sku_rec in skus:
            s = str(sku_rec.get("sku", ""))
            sku_strings.append(s)
            if s in seen_skus:
                duplicate_skus.append(s)
            seen_skus.add(s)

        # --- Check 2: Price anomalies (price <= 0) ---
        for price_rec in prices:
            idx = price_rec.get("variant_index", -1)
            price_val = price_rec.get("price", 0.0)
            if price_val <= 0:
                price_anomalies.append(
                    f"Variant {idx}: price {price_val} <= 0"
                )

        # --- Check 3: Coverage — every variant has a SKU ---
        sku_indices = {rec.get("variant_index") for rec in skus}
        for idx in range(len(variants)):
            if idx not in sku_indices:
                warnings.append(f"Variant {idx}: missing SKU record")

        # --- Check 4: Coverage — every variant has a price ---
        price_indices = {rec.get("variant_index") for rec in prices}
        for idx in range(len(variants)):
            if idx not in price_indices:
                warnings.append(f"Variant {idx}: missing price record")

        # --- Check 5: Orphan SKUs (SKU index beyond variant count) ---
        for sku_rec in skus:
            idx = sku_rec.get("variant_index", -1)
            if idx < 0 or idx >= len(variants):
                warnings.append(
                    f"SKU '{sku_rec.get('sku', '')}' references "
                    f"invalid variant index {idx}"
                )

        # --- Check 6: Orphan prices (price index beyond variant count) ---
        for price_rec in prices:
            idx = price_rec.get("variant_index", -1)
            if idx < 0 or idx >= len(variants):
                warnings.append(
                    f"Price record references invalid variant index {idx}"
                )

        is_valid = (
            len(duplicate_skus) == 0
            and len(price_anomalies) == 0
            and len(warnings) == 0
        )

        return {
            "status": "success",
            "is_valid": is_valid,
            "duplicate_skus": duplicate_skus,
            "price_anomalies": price_anomalies,
            "warnings": warnings,
        }
    except Exception as exc:
        return _fail(f"Validation failed: {exc}")


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
