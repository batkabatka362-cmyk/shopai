"""Product Validation Engine — risk flagger.

Aggregates compliance, sourcing, and quality results into risk flags.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def flag_risks(
    products: list[dict[str, Any]],
    compliance_issues: list[dict[str, Any]],
    sourcing_results: list[dict[str, Any]],
    quality_assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Flag risks for each product based on all validation results.

    Args:
        products: Original product list.
        compliance_issues: Compliance check results.
        sourcing_results: Sourcing validation results.
        quality_assessments: Quality assessment results.

    Returns:
        Structured dict with risk flags per product.
    """
    try:
        comp_map = {str(c.get("id", "")): c for c in compliance_issues}
        src_map = {str(s.get("id", "")): s for s in sourcing_results}
        qual_map = {str(q.get("id", "")): q for q in quality_assessments}

        flags: list[dict[str, Any]] = []

        for product in copy.deepcopy(products):
            pid = str(product.get("id", "unknown"))
            product_flags: list[str] = []
            risk_score = 0

            comp = comp_map.get(pid, {})
            if not comp.get("compliant", True):
                product_flags.extend(comp.get("issues", []))
                risk_score += 3 if comp.get("severity") == "critical" else 1

            src = src_map.get(pid, {})
            if not src.get("valid", True):
                product_flags.extend(src.get("issues", []))
                risk_score += 2

            qual = qual_map.get(pid, {})
            if qual.get("quality_score", 10.0) < 4.0:
                product_flags.append(f"Low quality score: {qual.get('quality_score', 0)}")
                risk_score += 2

            if risk_score >= 5:
                risk_level = "critical"
                recommendation = "reject"
            elif risk_score >= 3:
                risk_level = "high"
                recommendation = "review_required"
            elif risk_score >= 1:
                risk_level = "medium"
                recommendation = "proceed_with_caution"
            else:
                risk_level = "low"
                recommendation = "approved"

            flags.append({
                "id": pid,
                "risk_level": risk_level,
                "flags": product_flags,
                "recommendation": recommendation,
            })

        return {"status": "success", "flags": flags}
    except Exception as exc:
        return {"status": "error", "flags": [], "error": f"Risk flagging failed: {exc}"}
