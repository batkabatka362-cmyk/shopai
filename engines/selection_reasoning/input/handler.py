"""Selection Reasoning Engine — input validation and standardization.

Validates the incoming payload from the selection_decision engine,
normalizes field names, and ensures all required data is present
before the reasoning pipeline runs.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# --------------------------------------------------------------------------- #
#  Valid input constraints
# --------------------------------------------------------------------------- #
VALID_GOALS = {"profit", "growth", "balanced"}
VALID_PRODUCT_TYPES = {
    "general", "electronics", "apparel", "home", "beauty",
    "toys", "sports", "kitchen", "garden", "office",
}
MIN_INVESTMENT = 100.0
MAX_INVESTMENT = 1_000_000.0


def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the selection reasoning input.

    Args:
        input_payload: {
            data: {
                selected_product: dict  — required: the chosen product
                backup_product: dict    — optional: runner-up
                all_products: list      — all evaluated candidates
                decision_rationale: dict — why the product was chosen
                engine_results: dict    — upstream engine outputs
                confidence: dict        — confidence assessment
                goal: str               — profit|growth|balanced
                investment: float       — estimated investment
                product_type: str       — product category
                start_date: str         — optional plan start date
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

    # --- Validate selected product (required) ---
    selected = data.get("selected_product")
    if not selected or not isinstance(selected, dict):
        return _fail("'selected_product' is required and must be a dictionary")

    # Ensure product has an ID
    selected.setdefault("product_id", selected.get("id", "unknown"))
    selected.setdefault("product_name", selected.get("name", selected["product_id"]))
    data["selected_product"] = selected

    # --- Normalize backup product ---
    backup = data.get("backup_product")
    if backup and isinstance(backup, dict):
        backup.setdefault("product_id", backup.get("id", "backup"))
        backup.setdefault("product_name", backup.get("name", backup["product_id"]))
    else:
        data["backup_product"] = {}

    # --- Normalize all_products ---
    all_products = data.get("all_products", [])
    if not isinstance(all_products, list):
        all_products = []
    # Ensure selected product is in the list
    selected_id = selected.get("product_id")
    if not any(p.get("product_id") == selected_id for p in all_products):
        all_products.insert(0, selected)
    data["all_products"] = all_products

    # --- Normalize optional dicts ---
    data.setdefault("decision_rationale", {})
    data.setdefault("engine_results", {})
    data.setdefault("confidence", {})

    # --- Validate goal ---
    goal = str(data.get("goal", "balanced")).lower().strip()
    if goal not in VALID_GOALS:
        goal = "balanced"
    data["goal"] = goal

    # --- Validate investment ---
    investment = data.get("investment", 5000.0)
    try:
        investment = float(investment)
    except (TypeError, ValueError):
        investment = 5000.0
    investment = max(MIN_INVESTMENT, min(MAX_INVESTMENT, investment))
    data["investment"] = investment

    # --- Validate product type ---
    product_type = str(data.get("product_type", "general")).lower().strip()
    if product_type not in VALID_PRODUCT_TYPES:
        product_type = "general"
    data["product_type"] = product_type

    # --- Start date (optional, pass through) ---
    data.setdefault("start_date", None)

    return {
        "status": "success",
        "data": data,
        "meta": {
            "engine": "selection_reasoning",
            "goal": goal,
            "investment": investment,
            "product_type": product_type,
            "products_count": len(all_products),
            "timestamp": _timestamp(),
        },
        "error": None,
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized failure response."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "selection_reasoning",
            "confidence": 0,
            "timestamp": _timestamp(),
        },
        "error": {"reason": reason},
    }


def _timestamp() -> str:
    """Return current UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
