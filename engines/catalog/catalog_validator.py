"""Catalog Engine — catalog validator.

Validates catalog completeness: missing images, descriptions,
prices, categories, and data quality checks.
"""
from __future__ import annotations

import copy
from typing import Any


def validate_catalog(
    products: list[dict[str, Any]],
    categories: dict[str, Any],
    tag_assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate catalog completeness and quality.

    Args:
        products: Product records.
        categories: Organized categories.
        tag_assignments: Tag assignments.

    Returns:
        Structured dict with validation results.
    """
    try:
        prods = copy.deepcopy(products)
        issues: list[dict[str, Any]] = []

        checks_passed = 0
        checks_total = 0

        for prod in prods:
            pid = str(prod.get("id", ""))

            # Check required fields
            required = ["title", "price", "description"]
            for field in required:
                checks_total += 1
                if not prod.get(field):
                    issues.append({
                        "product_id": pid,
                        "issue": f"Missing {field}",
                        "severity": "high",
                    })
                else:
                    checks_passed += 1

            # Check image
            checks_total += 1
            if not prod.get("image") and not prod.get("images"):
                issues.append({
                    "product_id": pid,
                    "issue": "Missing image",
                    "severity": "medium",
                })
            else:
                checks_passed += 1

            # Check price validity
            checks_total += 1
            price = prod.get("price")
            if price is not None and (not isinstance(price, (int, float)) or price < 0):
                issues.append({
                    "product_id": pid,
                    "issue": "Invalid price",
                    "severity": "high",
                })
            else:
                checks_passed += 1

        # Check category coverage
        uncategorized = categories.get("uncategorized", {}).get("product_count", 0)
        if uncategorized > 0:
            issues.append({
                "product_id": "catalog",
                "issue": f"{uncategorized} products without category",
                "severity": "medium",
            })

        # Check tag coverage
        untagged = sum(1 for a in tag_assignments if a.get("tag_count", 0) == 0)
        if untagged > 0:
            issues.append({
                "product_id": "catalog",
                "issue": f"{untagged} products without tags",
                "severity": "low",
            })

        completeness = round(checks_passed / checks_total * 100, 1) if checks_total > 0 else 0.0

        return {
            "status": "success",
            "validation": {
                "issues": issues,
                "total_issues": len(issues),
                "checks_passed": checks_passed,
                "checks_total": checks_total,
            },
            "completeness_score": completeness,
        }
    except Exception as exc:
        return {
            "status": "error",
            "validation": {},
            "completeness_score": 0.0,
            "error": f"Catalog validation failed: {exc}",
        }
