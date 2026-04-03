"""Product Variant Engine — inventory linker.

Matches generated variants (by SKU) to existing inventory records.
Reports linked vs. unlinked counts so downstream systems know
which variants need new inventory entries.

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
    """Match variants to existing inventory records by SKU.

    Args:
        variants: List of GeneratedVariant dicts.
        skus: List of VariantSKU dicts from sku_builder.
        inventory_data: List of existing InventoryRecord dicts.

    Returns:
        Structured dict with per-SKU inventory link status.
    """
    try:
        skus = copy.deepcopy(skus)
        inventory_data = copy.deepcopy(inventory_data) if inventory_data else []

        # Build lookup from sku string -> inventory record
        inv_by_sku: dict[str, dict[str, Any]] = {}
        for record in inventory_data:
            sku_key = str(record.get("sku", "")).strip().upper()
            if sku_key:
                # If multiple records share a SKU, sum their stock
                if sku_key in inv_by_sku:
                    inv_by_sku[sku_key]["stock"] += int(record.get("stock", 0))
                else:
                    inv_by_sku[sku_key] = {
                        "stock": int(record.get("stock", 0)),
                        "warehouse": str(record.get("warehouse", "")),
                    }

        inventory_links: list[dict[str, Any]] = []
        linked_count = 0
        unlinked_count = 0

        for sku_entry in skus:
            sku_str = str(sku_entry.get("sku", "")).strip().upper()
            inv_match = inv_by_sku.get(sku_str)

            if inv_match is not None:
                inventory_links.append({
                    "sku": sku_entry.get("sku", ""),
                    "stock": inv_match["stock"],
                    "linked": True,
                })
                linked_count += 1
            else:
                inventory_links.append({
                    "sku": sku_entry.get("sku", ""),
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
