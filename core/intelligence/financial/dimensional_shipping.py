"""Dimensional weight shipping calculator.

Carriers charge whichever is greater: actual weight or dimensional weight.
dim_weight = (L x W x H) / divisor

Finds products with hidden shipping surcharges.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float


DIM_WEIGHT_DIVISORS = {
    "ups": 139,       # UPS domestic (inches)
    "fedex": 139,     # FedEx domestic (inches)
    "usps": 166,      # USPS (inches)
    "dhl": 5000,      # DHL (cm, international)
}


def analyze_dimensional_shipping(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate dimensional weight shipping costs per product."""
    results = []
    underpaying = 0

    for product in products:
        if not isinstance(product, dict):
            continue

        actual_weight = safe_float(product.get("weight", 0))
        if actual_weight > 100:
            actual_weight = actual_weight / 453.592  # grams to lbs

        length = safe_float(product.get("length", 0))
        width = safe_float(product.get("width", 0))
        height = safe_float(product.get("height", 0))

        if length == 0 or width == 0 or height == 0:
            continue

        dim_weights = {}
        for carrier, divisor in DIM_WEIGHT_DIVISORS.items():
            if carrier == "dhl":
                dim_w = (length * 2.54 * width * 2.54 * height * 2.54) / divisor
                dim_w = dim_w * 2.20462  # kg to lbs
            else:
                dim_w = (length * width * height) / divisor
            dim_weights[carrier] = round(dim_w, 2)

        billable_weights = {}
        for carrier, dim_w in dim_weights.items():
            billable = max(actual_weight, dim_w)
            billable_weights[carrier] = billable
            if dim_w > actual_weight:
                underpaying += 1

        product_name = product.get("title", product.get("name", "Unknown"))
        results.append({
            "product": product_name,
            "actual_weight_lbs": round(actual_weight, 2),
            "dim_weights": dim_weights,
            "billable_weights": billable_weights,
            "using_dim": any(dw > actual_weight for dw in dim_weights.values()),
        })

    return {
        "products_analyzed": len(results),
        "products_with_dim_surcharge": underpaying,
        "details": results[:20],
        "recommendation": (
            f"{underpaying} products may incur dimensional weight surcharges. "
            "Consider optimizing packaging to reduce L×W×H."
            if underpaying > 0 else "No dimensional weight issues detected."
        ),
    }
