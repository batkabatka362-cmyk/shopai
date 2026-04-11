"""Selection Decision Engine — input validation and standardization.

Validates the incoming payload, normalizes field names, and ensures
all required data is present before the pipeline runs.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# --------------------------------------------------------------------------- #
#  Required and optional fields
# --------------------------------------------------------------------------- #
VALID_GOALS = {"profit", "growth", "balanced"}
MIN_PRODUCTS = 1
MAX_PRODUCTS = 50


def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the selection decision input.

    Args:
        input_payload: {
            data: {
                products: list[dict] — product candidates with engine scores
                goal: str            — profit|growth|balanced (default: balanced)
                category: str        — product category (default: general)
            }
        }

    Returns:
        Standardized contract: {status, data, meta, error}
    """
    if not isinstance(input_payload, dict):
        return _fail("Input must be a dictionary")

    data = input_payload.get("data")
    if not isinstance(data, dict):
        return _fail("Input must contain a 'data' dictionary")

    data = copy.deepcopy(data)

    # --- Validate products ---
    products = data.get("products")
    if not products or not isinstance(products, list):
        return _fail("'products' list is required and must be non-empty")

    if len(products) < MIN_PRODUCTS:
        return _fail(f"Need at least {MIN_PRODUCTS} product(s), got {len(products)}")

    if len(products) > MAX_PRODUCTS:
        return _fail(f"Too many products ({len(products)}). Maximum is {MAX_PRODUCTS}")

    # --- Normalize each product ---
    normalized_products: list[dict[str, Any]] = []
    for i, product in enumerate(products):
        if not isinstance(product, dict):
            return _fail(f"Product at index {i} is not a dictionary")

        normalized = _normalize_product(product, i)
        normalized_products.append(normalized)

    data["products"] = normalized_products

    # --- Validate goal ---
    goal = str(data.get("goal", "balanced")).lower().strip()
    if goal not in VALID_GOALS:
        goal = "balanced"
    data["goal"] = goal

    # --- Validate category ---
    category = str(data.get("category", "general")).lower().strip()
    if not category:
        category = "general"
    data["category"] = category

    return {
        "status": "success",
        "data": data,
        "meta": {
            "engine": "selection_decision",
            "products_received": len(normalized_products),
            "goal": goal,
            "category": category,
            "timestamp": _timestamp(),
        },
        "error": None,
    }


def _normalize_product(product: dict[str, Any], index: int) -> dict[str, Any]:
    """Normalize a single product dict, ensuring required fields exist."""
    product.setdefault("product_id", product.get("id", f"product_{index}"))
    product.setdefault("product_name", product.get("name", product["product_id"]))

    # Ensure engine score dicts exist (even if empty)
    for engine_key in (
        "market_research", "trend_discovery", "profitability",
        "competition", "demand", "risk", "filter",
    ):
        if engine_key not in product:
            product[engine_key] = None

    return product


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized failure response."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "selection_decision",
            "confidence": 0,
            "timestamp": _timestamp(),
        },
        "error": {"reason": reason},
    }


def _timestamp() -> str:
    """Return current UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
