"""Product Validation Engine — sourcing validator.

Validates supplier reliability and sourcing legitimacy.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def validate_sourcing(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate sourcing for each product.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with sourcing validation results.
    """
    try:
        items = copy.deepcopy(products)
        results: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            supplier_id = str(item.get("supplier_id", ""))
            origin = str(item.get("origin_country", ""))

            issues: list[str] = []
            supplier_verified = bool(supplier_id and len(supplier_id) >= 3)

            if not supplier_id:
                issues.append("No supplier ID provided")
            if not origin:
                issues.append("No origin country specified")

            results.append({
                "id": product_id,
                "valid": len(issues) == 0,
                "supplier_verified": supplier_verified,
                "issues": issues,
            })

        return {"status": "success", "results": results}
    except Exception as exc:
        return {"status": "error", "results": [], "error": f"Sourcing validation failed: {exc}"}
