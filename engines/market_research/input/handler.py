"""Market Research Engine — input validation and standardization.

Validates engine contract:
  {status, data: {category, ...}, meta, error}

Standardizes field names, types, and defaults.
Never mutates original input.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.helpers import safe_float, safe_int


# Required and optional fields
SCHEMA = {
    "required": ["category"],
    "optional": {
        "products": [],
        "competitors": [],
        "search_data": {},
        "pricing": {},
        "reviews": [],
        "trend_signals": {},
        "sub_niche_pct": 0.1,
        "geographic_reach": 1.0,
        "price_range_fit": 0.5,
        "store_maturity": "new_store",
    },
}

VALID_STORE_MATURITIES = ("new_store", "established_1yr", "established_3yr", "market_leader")


def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Validate input follows engine contract, then standardize.

    Returns standardized payload or fail status.
    """
    # Contract structure check
    if not isinstance(input_payload, dict):
        return _fail("Input must be a dict")

    if input_payload.get("status") == "fail":
        return _fail("Input already failed: " + str(input_payload.get("error", "")))

    raw_data = input_payload.get("data")
    if not isinstance(raw_data, dict):
        return _fail("Input.data must be a dict")

    # Deep copy to avoid mutation
    data = copy.deepcopy(raw_data)

    # Required field check
    for field in SCHEMA["required"]:
        if not data.get(field):
            return _fail(f"Missing required field: {field}")

    # Standardize category
    data["category"] = str(data["category"]).strip().lower().replace(" ", "_").replace("-", "_")

    # Apply defaults for optional fields
    for field, default in SCHEMA["optional"].items():
        if field not in data:
            data[field] = default

    # Validate store_maturity
    if data.get("store_maturity") not in VALID_STORE_MATURITIES:
        data["store_maturity"] = "new_store"

    # Standardize numeric fields
    data["sub_niche_pct"] = max(0.01, min(1.0, safe_float(data.get("sub_niche_pct", 0.1))))
    data["geographic_reach"] = max(0.01, min(1.0, safe_float(data.get("geographic_reach", 1.0))))
    data["price_range_fit"] = max(0.01, min(1.0, safe_float(data.get("price_range_fit", 0.5))))

    # Standardize products
    if data.get("products"):
        data["products"] = _standardize_products(data["products"])

    # Standardize competitors
    if data.get("competitors"):
        data["competitors"] = _standardize_competitors(data["competitors"])

    return {
        "status": "success",
        "data": data,
        "meta": {
            "engine": "market_research",
            "input_fields": len(data),
            "products_count": len(data.get("products", [])),
            "competitors_count": len(data.get("competitors", [])),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _standardize_products(products: list) -> list[dict[str, Any]]:
    """Standardize product list — ensure consistent field types."""
    standardized = []
    for p in products:
        if not isinstance(p, dict):
            continue
        standardized.append({
            "id": str(p.get("id", "")),
            "title": str(p.get("title", p.get("name", ""))),
            "price": safe_float(p.get("price", 0)),
            "cost": safe_float(p.get("cost", 0)),
            "rating": safe_float(p.get("rating", 0)),
            "review_count": safe_int(p.get("review_count", p.get("reviews", 0))),
            "category": str(p.get("category", "")),
            "inventory_quantity": safe_int(p.get("inventory_quantity", 0)),
            **{k: v for k, v in p.items() if k not in ("id", "title", "name", "price", "cost", "rating", "review_count", "reviews", "category", "inventory_quantity")},
        })
    return standardized


def _standardize_competitors(competitors: list) -> list[dict[str, Any]]:
    """Standardize competitor list."""
    standardized = []
    for c in competitors:
        if not isinstance(c, dict):
            continue
        standardized.append({
            "name": str(c.get("name", c.get("store_name", ""))),
            "estimated_revenue": safe_float(c.get("estimated_revenue", 0)),
            "rating": safe_float(c.get("rating", 0)),
            "review_count": safe_int(c.get("review_count", 0)),
            "store_age_months": safe_int(c.get("store_age_months", 0)),
            **{k: v for k, v in c.items() if k not in ("name", "store_name", "estimated_revenue", "rating", "review_count", "store_age_months")},
        })
    return standardized


def _fail(reason: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "data": None,
        "meta": {"engine": "market_research", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
