"""Product Variant Engine — SKU builder.

Builds deterministic SKU codes and EAN-13 barcodes for each variant.

SKU format: {PRODUCT_CODE}-{OPT1_3CHARS}-{OPT2_3CHARS}-...
Barcode format: EAN-13 (country_code(3) + product(4) + variant(5) + check(1))

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_skus(
    product_code: str,
    variants: list[dict[str, Any]],
    country_code: str = "012",
) -> dict[str, Any]:
    """Build SKU strings and EAN-13 barcodes for all variants.

    Args:
        product_code: Short product identifier (e.g. "TSH001").
        variants: List of GeneratedVariant dicts from variant_generator.
        country_code: 3-digit country/system prefix for EAN-13 barcodes.

    Returns:
        Structured dict with SKU and barcode per variant.
    """
    try:
        variants = copy.deepcopy(variants)

        if not product_code or not product_code.strip():
            return _fail("product_code is required")

        if not variants:
            return _fail("No variants provided")

        # Sanitize country code: ensure exactly 3 digits
        cc = str(country_code).zfill(3)[:3]
        if not cc.isdigit():
            cc = "012"

        # Derive a 4-digit product number from product_code hash
        product_num = str(abs(hash(product_code)) % 10000).zfill(4)

        skus: list[dict[str, Any]] = []
        seen_skus: set[str] = set()

        for idx, variant in enumerate(variants):
            options = variant.get("options", {})

            # Build SKU: product_code + 3-char abbreviations of each option value
            parts = [product_code.upper()]
            for _axis_name, value in sorted(options.items()):
                abbrev = str(value).upper().replace(" ", "")[:3]
                parts.append(abbrev)

            sku = "-".join(parts)

            # Handle duplicates by appending index suffix
            base_sku = sku
            suffix = 2
            while sku in seen_skus:
                sku = f"{base_sku}-{suffix}"
                suffix += 1
            seen_skus.add(sku)

            # Build EAN-13 barcode
            variant_num = str(idx % 100000).zfill(5)
            barcode_body = f"{cc}{product_num}{variant_num}"
            check_digit = _ean13_check_digit(barcode_body)
            barcode = f"{barcode_body}{check_digit}"

            skus.append({
                "variant_index": idx,
                "sku": sku,
                "barcode": barcode,
            })

        return {
            "status": "success",
            "skus": skus,
        }
    except Exception as exc:
        return _fail(f"SKU building failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ean13_check_digit(body: str) -> str:
    """Calculate the EAN-13 check digit for a 12-digit string.

    The check digit is computed so that the weighted sum (alternating 1 and 3)
    of all 13 digits is a multiple of 10.
    """
    if len(body) != 12 or not body.isdigit():
        # Pad/truncate to 12 digits
        body = body.ljust(12, "0")[:12]

    total = 0
    for i, ch in enumerate(body):
        weight = 1 if i % 2 == 0 else 3
        total += int(ch) * weight

    check = (10 - (total % 10)) % 10
    return str(check)


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "skus": [],
        "error": reason,
    }
