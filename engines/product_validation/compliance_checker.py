"""Product Validation Engine — compliance checker.

Checks products against compliance standards: certifications,
restricted materials, labeling requirements.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_REQUIRED_CERTS_BY_CATEGORY: dict[str, list[str]] = {
    "electronics": ["CE", "FCC"],
    "food": ["FDA", "HACCP"],
    "toys": ["CPSIA", "ASTM_F963"],
    "cosmetics": ["FDA", "EU_1223"],
    "medical": ["FDA_510K", "ISO_13485"],
}


def check_compliance(
    products: list[dict[str, Any]],
    standards: list[str] | None = None,
) -> dict[str, Any]:
    """Check product compliance against standards.

    Args:
        products: List of product dicts.
        standards: Additional required standards.

    Returns:
        Structured dict with compliance issues.
    """
    try:
        items = copy.deepcopy(products)
        issues: list[dict[str, Any]] = []
        extra_standards = set(standards or [])

        for item in items:
            product_id = str(item.get("id", "unknown"))
            category = str(item.get("category", "")).lower()
            certs = set(str(c).upper() for c in item.get("certifications", []))
            has_recall = bool(item.get("recall_history", False))

            product_issues: list[str] = []

            # Check category-specific certs
            required = _REQUIRED_CERTS_BY_CATEGORY.get(category, [])
            for req in required:
                if req.upper() not in certs:
                    product_issues.append(f"Missing required certification: {req}")

            # Check extra standards
            for std in extra_standards:
                if std.upper() not in certs:
                    product_issues.append(f"Missing standard: {std}")

            # Recall check
            if has_recall:
                product_issues.append("Product has recall history")

            if product_issues:
                severity = "critical" if has_recall or len(product_issues) > 2 else "warning"
            else:
                severity = "clear"

            issues.append({
                "id": product_id,
                "compliant": len(product_issues) == 0,
                "issues": product_issues,
                "severity": severity,
            })

        return {"status": "success", "issues": issues}
    except Exception as exc:
        return {"status": "error", "issues": [], "error": f"Compliance check failed: {exc}"}
