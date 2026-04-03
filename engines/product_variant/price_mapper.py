"""Product Variant Engine — price mapper.

Applies per-option price adjustments to compute the final price of each variant.

Each option axis can define price_adjustments: {"value_name": delta}.
Final price = base_price + sum of all applicable adjustments.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def map_prices(
    variants: list[dict[str, Any]],
    base_price: float,
    options: list[dict[str, Any]],
    compare_at_price: float | None = None,
) -> dict[str, Any]:
    """Calculate final price for every variant.

    Args:
        variants: List of GeneratedVariant dicts.
        base_price: Product base price before adjustments.
        options: List of OptionAxis dicts (may include price_adjustments).
        compare_at_price: Optional original/compare-at price for the product.

    Returns:
        Structured dict with per-variant price info.
    """
    try:
        variants = copy.deepcopy(variants)
        options = copy.deepcopy(options)

        if base_price < 0:
            return _fail("base_price must be non-negative")

        if not variants:
            return _fail("No variants provided")

        # Build a lookup: axis_name -> {value: adjustment}
        adj_map: dict[str, dict[str, float]] = {}
        for axis in options:
            name = axis.get("name", "")
            adjustments = axis.get("price_adjustments", {})
            if isinstance(adjustments, dict) and name:
                adj_map[name] = {
                    str(k): float(v)
                    for k, v in adjustments.items()
                }

        prices: list[dict[str, Any]] = []

        for idx, variant in enumerate(variants):
            variant_options = variant.get("options", {})
            total_adjustment = 0.0

            for axis_name, value in variant_options.items():
                axis_adj = adj_map.get(axis_name, {})
                delta = axis_adj.get(str(value), 0.0)
                total_adjustment += delta

            final_price = round(base_price + total_adjustment, 2)

            # Ensure price doesn't go negative
            if final_price < 0:
                final_price = 0.0

            # Compute compare-at price with same adjustment if provided
            variant_compare: float | None = None
            if compare_at_price is not None and compare_at_price > 0:
                variant_compare = round(compare_at_price + total_adjustment, 2)
                if variant_compare < 0:
                    variant_compare = 0.0
                # compare_at must be >= price to make sense; if not, drop it
                if variant_compare <= final_price:
                    variant_compare = None

            prices.append({
                "variant_index": idx,
                "price": final_price,
                "adjustment": round(total_adjustment, 2),
                "compare_at_price": variant_compare,
            })

        return {
            "status": "success",
            "prices": prices,
        }
    except Exception as exc:
        return _fail(f"Price mapping failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "prices": [],
        "error": reason,
    }
