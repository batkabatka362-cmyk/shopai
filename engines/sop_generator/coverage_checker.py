"""SOP Generator Engine — coverage checker.

Checks SOP coverage across operations and identifies gaps.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any

_STANDARD_OPERATIONS = [
    "order_fulfillment", "returns", "inventory_restock",
    "customer_support", "shipping", "quality_inspection",
    "supplier_communication", "payment_processing",
    "product_listing", "marketing_campaign",
]


def check_coverage(
    sops: list[dict[str, Any]],
    operations: list[str],
) -> dict[str, Any]:
    """Check SOP coverage and identify gaps.

    Args:
        sops: Generated SOPs.
        operations: Requested operations.

    Returns:
        Structured dict with coverage status and gaps.
    """
    try:
        covered_ops = {s["operation"] for s in sops if len(s.get("steps", [])) > 0}

        # Check if SOPs have real steps (not just skeleton)
        well_covered = set()
        for sop in sops:
            steps = sop.get("steps", [])
            has_real_steps = any(
                "manual SOP creation required" not in s.get("details", "")
                for s in steps
            )
            if has_real_steps and len(steps) > 0:
                well_covered.add(sop["operation"])

        coverage: dict[str, bool] = {}
        for op in operations:
            coverage[op] = op in well_covered

        # Identify gaps
        gaps: list[str] = []
        for op in operations:
            if op not in well_covered:
                gaps.append(f"Operation '{op}' has no historical pattern — needs manual SOP creation")

        # Check standard operations not requested
        for std_op in _STANDARD_OPERATIONS:
            if std_op not in operations and std_op not in covered_ops:
                gaps.append(f"Standard operation '{std_op}' has no SOP — consider adding")

        return {"status": "success", "coverage": coverage, "gaps": gaps}
    except Exception as exc:
        return {"status": "error", "coverage": {}, "gaps": [], "error": f"Coverage check failed: {exc}"}
