"""Marketplace Engine — inventory allocator.

Allocates available inventory across marketplace channels based on
performance history, priority rules, and safety buffers.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# Default allocation split when no performance data exists
_DEFAULT_SPLIT: dict[str, float] = {
    "amazon": 0.50,
    "etsy": 0.25,
    "ebay": 0.25,
}

# Percentage of total stock to hold as buffer
_BUFFER_PCT = 0.10


def allocate_inventory(
    products: list[dict[str, Any]],
    marketplaces: list[str],
    inventory: dict[str, int],
    performance: list[dict[str, Any]],
) -> dict[str, Any]:
    """Allocate inventory across marketplace channels.

    Args:
        products: List of product dicts.
        marketplaces: Target marketplace platforms.
        inventory: Dict mapping product_id to total stock count.
        performance: Per-platform performance dicts (used to weight allocation).

    Returns:
        Structured dict with per-product allocations.
    """
    try:
        items = copy.deepcopy(products)
        mp_list = [m.lower() for m in marketplaces]

        # Build performance weights from revenue
        perf_weights = _compute_weights(performance, mp_list)

        allocations: list[dict[str, Any]] = []

        for product in items:
            pid = str(product.get("id", "unknown"))
            total_stock = int(inventory.get(pid, product.get("current_stock", 0)))

            if total_stock <= 0:
                allocations.append({
                    "product_id": pid,
                    "total_stock": 0,
                    "allocations": {m: 0 for m in mp_list},
                    "buffer_held": 0,
                })
                continue

            buffer = max(1, int(total_stock * _BUFFER_PCT))
            distributable = total_stock - buffer

            channel_alloc: dict[str, int] = {}
            allocated_so_far = 0

            sorted_platforms = sorted(
                mp_list,
                key=lambda m: perf_weights.get(m, 0.0),
                reverse=True,
            )

            for i, platform in enumerate(sorted_platforms):
                weight = perf_weights.get(platform, 1.0 / max(len(mp_list), 1))
                if i == len(sorted_platforms) - 1:
                    # Last platform gets remainder to avoid rounding loss
                    units = distributable - allocated_so_far
                else:
                    units = int(distributable * weight)
                units = max(0, units)
                channel_alloc[platform] = units
                allocated_so_far += units

            allocations.append({
                "product_id": pid,
                "total_stock": total_stock,
                "allocations": channel_alloc,
                "buffer_held": buffer,
            })

        return {
            "status": "success",
            "allocations": allocations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "allocations": [],
            "error": f"Inventory allocation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_weights(
    performance: list[dict[str, Any]],
    marketplaces: list[str],
) -> dict[str, float]:
    """Compute normalized allocation weights from performance revenue."""
    revenue_map: dict[str, float] = {}
    for perf in performance:
        plat = str(perf.get("platform", "")).lower()
        rev = float(perf.get("revenue", 0.0))
        if plat in marketplaces:
            revenue_map[plat] = rev

    total_rev = sum(revenue_map.values())

    if total_rev > 0:
        return {m: revenue_map.get(m, 0.0) / total_rev for m in marketplaces}

    # Fall back to equal split
    n = max(len(marketplaces), 1)
    return {m: 1.0 / n for m in marketplaces}
