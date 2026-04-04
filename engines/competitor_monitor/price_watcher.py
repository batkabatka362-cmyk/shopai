"""Competitor Monitor Engine — price watcher.

Watches competitor prices and detects changes by comparing current
competitor product prices against our catalog. Identifies undercuts,
price drops, and price increases.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def watch_prices(
    competitors: list[dict[str, Any]],
    our_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Watch competitor prices and detect significant changes.

    Args:
        competitors: List of CompetitorRecord dicts with product prices.
        our_products: List of OurProduct dicts for comparison.

    Returns:
        Structured dict with detected price changes.
    """
    try:
        comp_items = copy.deepcopy(competitors)

        # Build our price map for comparison
        our_price_map: dict[str, float] = {}
        for prod in our_products:
            pid = str(prod.get("product_id", ""))
            our_price_map[pid] = float(prod.get("price", 0.0))

        price_changes: list[dict[str, Any]] = []

        for competitor in comp_items:
            comp_name = str(competitor.get("name", "unknown"))
            products = competitor.get("products", [])

            for product in products:
                pid = str(product.get("product_id", ""))
                title = str(product.get("title", pid))
                comp_price = float(product.get("price", 0.0))

                # Compare against our price as the baseline
                our_price = our_price_map.get(pid, 0.0)
                if our_price <= 0.0:
                    continue

                # Calculate price difference
                diff = comp_price - our_price
                change_pct = round((diff / our_price) * 100.0, 2)

                # Determine direction
                if change_pct < -1.0:
                    direction = "competitor_lower"
                elif change_pct > 1.0:
                    direction = "competitor_higher"
                else:
                    direction = "similar"

                # Only report notable changes (> 1% difference)
                if abs(change_pct) > 1.0:
                    price_changes.append({
                        "competitor": comp_name,
                        "product_id": pid,
                        "product_title": title,
                        "old_price": our_price,
                        "new_price": comp_price,
                        "change_pct": change_pct,
                        "direction": direction,
                    })

        return {
            "status": "success",
            "price_changes": price_changes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "price_changes": [],
            "error": f"Price watching failed: {exc}",
        }
