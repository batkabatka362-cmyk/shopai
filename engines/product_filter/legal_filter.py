"""Product Filter Engine — legal filter.

Filters products that fail legal compliance checks: blocked categories,
restricted origin countries, and flagged restricted items.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default restricted categories (regulatory / liability)
# ---------------------------------------------------------------------------

_DEFAULT_RESTRICTED = {
    "weapons", "tobacco", "explosives", "controlled_substances",
    "hazardous_materials", "counterfeit", "recalled",
}


def filter_by_legal(
    products: list[dict[str, Any]],
    blocked_categories: list[str] | None = None,
    allowed_countries: list[str] | None = None,
) -> dict[str, Any]:
    """Filter products by legal compliance.

    Args:
        products: List of ProductCandidate dicts.
        blocked_categories: Additional category blocklist.
        allowed_countries: If set, only these origin countries are allowed.

    Returns:
        Structured dict with passed and rejected lists.
    """
    try:
        items = copy.deepcopy(products)
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        compliance_notes: list[str] = []

        full_blocked = _DEFAULT_RESTRICTED.copy()
        if blocked_categories:
            full_blocked.update(c.lower().strip() for c in blocked_categories)

        allowed_set = (
            {c.upper().strip() for c in allowed_countries}
            if allowed_countries else None
        )

        for item in items:
            product_id = str(item.get("id", "unknown"))
            category = str(item.get("category", "")).lower().strip()
            origin = str(item.get("origin_country", "")).upper().strip()
            is_restricted = bool(item.get("restricted", False))

            reason = None

            if is_restricted:
                reason = "Product is flagged as restricted"
            elif category in full_blocked:
                reason = f"Category '{category}' is blocked"
            elif allowed_set and origin and origin not in allowed_set:
                reason = f"Origin country '{origin}' not in allowed list"

            if reason:
                item["rejection_stage"] = "legal_filter"
                item["rejection_reason"] = reason
                rejected.append(item)
                compliance_notes.append(f"{product_id}: {reason}")
            else:
                passed.append(item)

        return {
            "status": "success",
            "passed": passed,
            "rejected": rejected,
            "compliance_notes": compliance_notes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "passed": [],
            "rejected": [],
            "error": f"Legal filter failed: {exc}",
        }
