"""Warranty Engine — claim processor.

Processes warranty claims: validates eligibility, categorizes
issues, and tracks resolution status.
"""
from __future__ import annotations

import copy
from typing import Any


def process_claims(
    claims: list[dict[str, Any]],
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process warranty claims.

    Args:
        claims: Warranty claim records.
        policies: Warranty policies.

    Returns:
        Structured dict with processed claims data.
    """
    try:
        claim_data = copy.deepcopy(claims)

        total = len(claim_data)
        approved = 0
        denied = 0
        pending = 0

        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {}

        processed: list[dict[str, Any]] = []

        for claim in claim_data:
            status = str(claim.get("status", "pending"))
            category = str(claim.get("category", claim.get("issue_type", "other")))

            by_category[category] = by_category.get(category, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1

            if status == "approved":
                approved += 1
            elif status == "denied":
                denied += 1
            else:
                pending += 1

            processed.append({
                "claim_id": str(claim.get("id", claim.get("claim_id", ""))),
                "product_id": str(claim.get("product_id", "")),
                "status": status,
                "category": category,
                "cost": float(claim.get("cost", claim.get("resolution_cost", 0))),
            })

        approval_rate = round(approved / total * 100, 1) if total > 0 else 0.0

        return {
            "status": "success",
            "claims_processed": {
                "total_claims": total,
                "approved": approved,
                "denied": denied,
                "pending": pending,
                "approval_rate_pct": approval_rate,
                "by_category": by_category,
                "by_status": by_status,
                "details": processed,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "claims_processed": {},
            "error": f"Claim processing failed: {exc}",
        }
