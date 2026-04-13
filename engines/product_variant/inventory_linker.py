"""Product Variant Engine — inventory linker.

Matches generated variant SKUs against existing inventory records.
Links each variant to its inventory stock level if a matching SKU is found.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def link_inventory(
    variants: list[dict[str, Any]],
    skus: list[dict[str, Any]],
    inventory_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match variant SKUs to existing inventory records.

    Args:
        variants: List of variant dicts from variant_generator.
        skus: List of SKU dicts from sku_builder.
        inventory_data: List of existing inventory records with 'sku' and 'stock'.

    Returns:
        Structured dict with inventory link records and counts.
    """
    try:
        skus = copy.deepcopy(skus)
        inventory_data = copy.deepcopy(inventory_data) if inventory_data else []

        # Build inventory lookup by SKU (case-insensitive)
        inv_map: dict[str, dict[str, Any]] = {}
        for record in inventory_data:
            sku_key = str(record.get("sku", "")).strip().upper()
            if sku_key:
                inv_map[sku_key] = record

        inventory_links: list[dict[str, Any]] = []
        linked_count = 0
        unlinked_count = 0

        for sku_record in skus:
            sku_str = str(sku_record.get("sku", "")).strip().upper()
            inv_match = inv_map.get(sku_str)

            if inv_match:
                stock = int(inv_match.get("stock", 0))
                inventory_links.append({
                    "sku": sku_record.get("sku", ""),
                    "stock": stock,
                    "linked": True,
                })
                linked_count += 1
            else:
                inventory_links.append({
                    "sku": sku_record.get("sku", ""),
                    "stock": 0,
                    "linked": False,
                })
                unlinked_count += 1

        return {
            "status": "success",
            "inventory": inventory_links,
            "linked_count": linked_count,
            "unlinked_count": unlinked_count,
        }
    except Exception as exc:
        return _fail(f"Inventory linking failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "inventory": [],
        "linked_count": 0,
        "unlinked_count": 0,
        "error": reason,
    }
