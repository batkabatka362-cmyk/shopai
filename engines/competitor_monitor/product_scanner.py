"""Competitor Monitor Engine — product scanner.

Scans for new competitor products that don't exist in our catalog.
Assesses threat level based on category overlap and pricing.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def scan_products(
    competitors: list[dict[str, Any]],
    our_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Scan for new competitor products not in our catalog.

    Args:
        competitors: List of CompetitorRecord dicts with products.
        our_products: List of OurProduct dicts for comparison.

    Returns:
        Structured dict with newly detected competitor products.
    """
    try:
        comp_items = copy.deepcopy(competitors)

        # Build set of our product IDs and categories
        our_pids: set[str] = set()
        our_categories: set[str] = set()
        our_price_by_cat: dict[str, list[float]] = {}

        for prod in our_products:
            pid = str(prod.get("product_id", ""))
            cat = str(prod.get("category", ""))
            price = float(prod.get("price", 0.0))
            our_pids.add(pid)
            if cat:
                our_categories.add(cat)
                our_price_by_cat.setdefault(cat, []).append(price)

        # Compute avg price per category for threat assessment
        avg_price_by_cat: dict[str, float] = {}
        for cat, prices in our_price_by_cat.items():
            avg_price_by_cat[cat] = sum(prices) / len(prices) if prices else 0.0

        new_products: list[dict[str, Any]] = []

        for competitor in comp_items:
            comp_name = str(competitor.get("name", "unknown"))
            products = competitor.get("products", [])

            for product in products:
                pid = str(product.get("product_id", ""))
                title = str(product.get("title", pid))
                price = float(product.get("price", 0.0))
                category = str(product.get("category", ""))

                # Skip products we already carry
                if pid in our_pids:
                    continue

                # Assess threat level
                if category in our_categories:
                    our_avg = avg_price_by_cat.get(category, 0.0)
                    if our_avg > 0 and price < our_avg * 0.8:
                        threat = "high"
                    elif our_avg > 0 and price < our_avg:
                        threat = "medium"
                    else:
                        threat = "low"
                else:
                    threat = "low"

                new_products.append({
                    "competitor": comp_name,
                    "product_id": pid,
                    "product_title": title,
                    "price": price,
                    "category": category,
                    "threat_level": threat,
                })

        return {
            "status": "success",
            "new_products": new_products,
        }
    except Exception as exc:
        return {
            "status": "error",
            "new_products": [],
            "error": f"Product scanning failed: {exc}",
        }
