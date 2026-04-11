"""Competition Analyzer Engine — price comparator.

Compare pricing across competitors for the same or similar products.
"""
from __future__ import annotations

import copy
from typing import Any


def compare_prices(
    **kwargs: Any,
) -> dict[str, Any]:
    """Compare pricing across competitors.

    Args:
        **kwargs: Must include 'competitors' list and 'products' list.

    Returns:
        Structured dict with price comparison data.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        products = kwargs.get("products", [])

        comparisons: list[dict[str, Any]] = []
        for comp in competitors:
            comp_id = str(comp.get("id", "unknown"))
            comp_prices = comp.get("prices", {})
            our_products_matched = 0

            for prod in products:
                pid = str(prod.get("id", ""))
                our_price = float(prod.get("price", 0))
                comp_price = float(comp_prices.get(pid, 0))

                if comp_price > 0 and our_price > 0:
                    our_products_matched += 1
                    diff_pct = round((comp_price - our_price) / our_price * 100, 1)
                    comparisons.append({
                        "competitor_id": comp_id,
                        "product_id": pid,
                        "our_price": our_price,
                        "competitor_price": comp_price,
                        "difference_pct": diff_pct,
                        "we_are_cheaper": diff_pct > 0,
                    })

        return {
            "status": "success",
            "result": {
                "comparisons": comparisons,
                "total_comparisons": len(comparisons),
                "cheaper_count": sum(1 for c in comparisons if c["we_are_cheaper"]),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Price comparison failed: {exc}"}
