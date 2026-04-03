"""Product Variant Engine — SKU builder.

Builds SKU strings and EAN-13 barcodes for each variant.

SKU format: {PRODUCT_CODE}-{OPT1_3CHARS}-{OPT2_3CHARS}-...
Barcode: EAN-13 (country_code(3) + product(4) + variant(5) + check(1))

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# Default country code prefix for EAN-13
_DEFAULT_COUNTRY_CODE = "012"


def build_skus(
    product_code: str,
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build SKU strings and EAN-13 barcodes for all variants.

    Args:
        product_code: Base product code string.
        variants: List of variant dicts from variant_generator.

    Returns:
        Structured dict with SKU and barcode records.
    """
    try:
        variants = copy.deepcopy(variants)

        if not product_code:
            return _fail("Product code is required")
        if not variants:
            return _fail("No variants to build SKUs for")

        product_code_clean = product_code.strip().upper()

        # Derive a 4-digit product number from the product code
        product_num = _product_code_to_digits(product_code_clean, 4)

        skus: list[dict[str, Any]] = []

        for idx, variant in enumerate(variants):
            options = variant.get("options", {})

            # Build SKU: PRODUCT_CODE-OPT1-OPT2-...
            option_parts = []
            for _key in sorted(options.keys()):
                val = str(options[_key]).upper()
                # Take first 3 characters, pad if needed
                abbr = val[:3].ljust(3, "X")
                option_parts.append(abbr)

            sku = "-".join([product_code_clean] + option_parts)

            # Build EAN-13 barcode
            variant_num = str(idx + 1).zfill(5)
            barcode_body = _DEFAULT_COUNTRY_CODE + product_num + variant_num
            check_digit = _ean13_check_digit(barcode_body)
            barcode = barcode_body + str(check_digit)

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

def _product_code_to_digits(code: str, length: int) -> str:
    """Convert a product code to a fixed-length digit string.

    Uses ordinal sum modulo to derive a reproducible numeric code.
    """
    num = 0
    for ch in code:
        num = (num * 31 + ord(ch)) % (10 ** length)
    return str(num).zfill(length)


def _ean13_check_digit(body: str) -> int:
    """Calculate EAN-13 check digit for a 12-digit string.

    The check digit is calculated so that the weighted sum of all 13 digits
    (alternating weights 1 and 3) is a multiple of 10.
    """
    if len(body) != 12:
        raise ValueError(f"EAN-13 body must be 12 digits, got {len(body)}")

    total = 0
    for i, ch in enumerate(body):
        digit = int(ch)
        weight = 1 if i % 2 == 0 else 3
        total += digit * weight

    remainder = total % 10
    return (10 - remainder) % 10


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "skus": [],
        "error": reason,
    }
