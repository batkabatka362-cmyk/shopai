"""Product Variant Engine — price mapper.

Applies per-option price adjustments to compute final variant prices.

Each option axis can define price_adjustments: {"value": delta}.
Final price = base_price + sum(adjustments).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def map_prices(
    variants: list[dict[str, Any]],
    base_price: float,
    options: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate final price per variant based on option adjustments.

    Args:
        variants: List of variant dicts from variant_generator.
        base_price: Base product price.
        options: List of option axis dicts, each may include
            'price_adjustments': {"value_name": delta_float}.

    Returns:
        Structured dict with per-variant price records.
    """
    try:
        variants = copy.deepcopy(variants)
        options = copy.deepcopy(options)

        if base_price < 0:
            return _fail("Base price cannot be negative")
        if not variants:
            return _fail("No variants to price")

        # Build adjustment lookup: {axis_name: {value: delta}}
        adj_map: dict[str, dict[str, float]] = {}
        for opt in options:
            name = opt.get("name", "")
            adjustments = opt.get("price_adjustments", {})
            if name and isinstance(adjustments, dict):
                adj_map[name] = {
                    str(k): float(v) for k, v in adjustments.items()
                }

        prices: list[dict[str, Any]] = []

        for idx, variant in enumerate(variants):
            variant_options = variant.get("options", {})
            total_adjustment = 0.0

            for axis_name, axis_value in variant_options.items():
                axis_adj = adj_map.get(axis_name, {})
                delta = axis_adj.get(str(axis_value), 0.0)
                total_adjustment += delta

            final_price = round(base_price + total_adjustment, 2)

            # compare_at_price is the base price when there is a negative
            # adjustment (i.e. the variant is cheaper than base), otherwise
            # it equals the final price (no strike-through).
            compare_at_price = round(base_price, 2) if total_adjustment < 0 else final_price

            prices.append({
                "variant_index": idx,
                "price": final_price,
                "adjustment": round(total_adjustment, 2),
                "compare_at_price": compare_at_price,
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
