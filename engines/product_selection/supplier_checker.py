"""Product Selection Engine — supplier checker.

Verifies supplier availability for each candidate product by matching
product IDs against the supplier catalog.
"""
from __future__ import annotations

import copy
from typing import Any


def check_suppliers(
    candidates: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify supplier availability for candidates.

    Args:
        candidates: List of candidate product dicts.
        suppliers: List of supplier records.

    Returns:
        Structured dict with supplier-checked candidates.
    """
    try:
        items = copy.deepcopy(candidates)
        supplier_map: dict[str, dict[str, Any]] = {}
        for s in suppliers:
            for pid in s.get("product_ids", []):
                supplier_map[str(pid)] = {
                    "supplier_id": str(s.get("id", "")),
                    "name": str(s.get("name", "")),
                    "reliability": float(s.get("reliability", 0.5)),
                    "lead_time_days": int(s.get("lead_time_days", 14)),
                }

        checked: list[dict[str, Any]] = []
        for item in items:
            pid = str(item.get("id", ""))
            supplier = supplier_map.get(pid)
            item["supplier_available"] = supplier is not None
            item["supplier"] = supplier if supplier else {}
            checked.append(item)

        return {
            "status": "success",
            "checked": checked,
            "available_count": sum(1 for c in checked if c["supplier_available"]),
        }
    except Exception as exc:
        return {
            "status": "error",
            "checked": [],
            "error": f"Supplier checking failed: {exc}",
        }
