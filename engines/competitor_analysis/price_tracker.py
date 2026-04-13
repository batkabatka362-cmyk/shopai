"""Competitor Analysis Engine — price tracker.

Track competitor price changes over time.
"""
from __future__ import annotations

import copy
from typing import Any


def track_prices(
    **kwargs: Any,
) -> dict[str, Any]:
    """Track competitor price changes.

    Args:
        **kwargs: Must include competitors and tracked_products.

    Returns:
        Structured dict with price change tracking.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        tracked_products = kwargs.get("tracked_products", [])

        price_changes: list[dict[str, Any]] = []

        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            changes = comp.get("recent_price_changes", [])

            for change in changes:
                pid = str(change.get("product_id", ""))
                old_price = float(change.get("old_price", 0))
                new_price = float(change.get("new_price", 0))
                if old_price > 0:
                    change_pct = round((new_price - old_price) / old_price * 100, 1)
                else:
                    change_pct = 0.0

                price_changes.append({
                    "competitor_id": cid,
                    "product_id": pid,
                    "old_price": old_price,
                    "new_price": new_price,
                    "change_pct": change_pct,
                    "direction": "up" if change_pct > 0 else "down" if change_pct < 0 else "unchanged",
                    "date": change.get("date", ""),
                })

        return {
            "status": "success",
            "result": {
                "price_changes": price_changes,
                "total_changes": len(price_changes),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Price tracking failed: {exc}"}
