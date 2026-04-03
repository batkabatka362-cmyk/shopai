"""Product Selection Engine — candidate generator.

Generates candidate products from market data, applying basic demand
and category filters to produce an initial candidate list.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_candidates(
    market_data: list[dict[str, Any]],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    """Generate candidate products from market data.

    Args:
        market_data: Raw market data items.
        criteria: Selection criteria with optional min_demand, categories.

    Returns:
        Structured dict with candidate products.
    """
    try:
        items = copy.deepcopy(market_data)
        candidates: list[dict[str, Any]] = []

        min_demand = float(criteria.get("min_demand", 0.0))
        target_categories = criteria.get("categories", [])

        for item in items:
            pid = str(item.get("id", ""))
            name = str(item.get("name", ""))
            category = str(item.get("category", ""))
            demand = float(item.get("demand_score", 0.0))
            price = float(item.get("price", 0.0))
            cost = float(item.get("cost", 0.0))

            if demand < min_demand:
                continue
            if target_categories and category not in target_categories:
                continue

            margin = round((price - cost) / price, 4) if price > 0 else 0.0

            candidates.append({
                "id": pid,
                "name": name,
                "category": category,
                "demand_score": demand,
                "price": price,
                "cost": cost,
                "margin": margin,
            })

        return {
            "status": "success",
            "candidates": candidates,
        }
    except Exception as exc:
        return {
            "status": "error",
            "candidates": [],
            "error": f"Candidate generation failed: {exc}",
        }
