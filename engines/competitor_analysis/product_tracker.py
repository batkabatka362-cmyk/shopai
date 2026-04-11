"""Competitor Analysis Engine — product tracker.

Track competitor product launches and discontinuations.
"""
from __future__ import annotations

import copy
from typing import Any


def track_products(
    **kwargs: Any,
) -> dict[str, Any]:
    """Track competitor product changes.

    Args:
        **kwargs: Must include competitors.

    Returns:
        Structured dict with product tracking data.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))

        new_products: list[dict[str, Any]] = []

        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            name = comp.get("name", cid)
            launches = comp.get("recent_launches", [])

            for launch in launches:
                new_products.append({
                    "competitor_id": cid,
                    "competitor_name": name,
                    "product_name": launch.get("name", "Unknown"),
                    "category": launch.get("category", ""),
                    "price": float(launch.get("price", 0)),
                    "launch_date": launch.get("date", ""),
                })

        return {
            "status": "success",
            "result": {
                "new_products": new_products,
                "total_launches": len(new_products),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Product tracking failed: {exc}"}
