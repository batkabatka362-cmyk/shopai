"""Discount Strategy Engine — margin analyzer.

Analyzes current margins per product, determines safe discount room,
and identifies the maximum discount depth before hitting the margin floor.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Margin floor by goal — how low we allow margin to go
# ---------------------------------------------------------------------------

_GOAL_MARGIN_FLOORS: dict[str, float] = {
    "clear_inventory": 0.02,        # near break-even is OK for clearance
    "boost_revenue": 0.10,          # maintain some profit
    "acquire_customers": 0.05,      # accept thin margins for acquisition
    "reactivate": 0.08,             # slight concession for reactivation
}

_DEFAULT_MARGIN_FLOOR = 0.10


def analyze_margins(
    products: list[dict[str, Any]],
    goal: str,
) -> dict[str, Any]:
    """Analyze margins for all products and determine safe discount room.

    Args:
        products: List of ProductInput dicts with price, cogs, current_margin, etc.
        goal: Business goal driving the discount (clear_inventory, boost_revenue, etc.).

    Returns:
        Structured dict with per-product MarginAnalysis and aggregated summary.
    """
    try:
        prods = copy.deepcopy(products)
        if not prods:
            return {
                "status": "error",
                "analyses": [],
                "summary": {},
                "error": "No products provided",
            }

        margin_floor = _GOAL_MARGIN_FLOORS.get(goal.lower(), _DEFAULT_MARGIN_FLOOR)
        analyses: list[dict[str, Any]] = []

        for prod in prods:
            analysis = _analyze_single_product(prod, margin_floor)
            analyses.append(analysis)

        summary = _compute_summary(analyses, margin_floor)

        return {
            "status": "success",
            "analyses": analyses,
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "summary": {},
            "error": f"Margin analysis failed: {exc}",
        }


def _analyze_single_product(
    product: dict[str, Any],
    margin_floor: float,
) -> dict[str, Any]:
    """Analyze margin for a single product.

    Max discount pct = (current_margin - margin_floor) / (1 - margin_floor)
    This formula ensures that after applying discount_pct to price,
    the resulting margin is exactly at margin_floor.

    Derivation:
      discounted_price = price * (1 - d)
      new_margin = (discounted_price - cogs) / discounted_price
      Set new_margin = margin_floor:
      margin_floor = 1 - cogs / (price * (1 - d))
      Solve for d: d = 1 - cogs / (price * (1 - margin_floor))
      Which simplifies to: d = (current_margin - margin_floor) / (1 - margin_floor)
      when current_margin = (price - cogs) / price.
    """
    price = float(product.get("price", 0.0))
    cogs = float(product.get("cogs", 0.0))
    product_id = str(product.get("id", "unknown"))
    title = str(product.get("title", ""))

    # Compute actual current margin
    if price > 0:
        current_margin = (price - cogs) / price
    else:
        current_margin = 0.0

    # Override with provided margin if available and price/cogs are missing
    if price <= 0 or cogs <= 0:
        current_margin = float(product.get("current_margin", 0.0))

    # Max discount before hitting floor
    if current_margin > margin_floor and price > 0:
        max_discount_pct = (current_margin - margin_floor) / (1.0 - margin_floor)
        # Also ensure discounted price >= cogs (absolute floor)
        absolute_max = 1.0 - (cogs / price) if price > 0 and cogs > 0 else max_discount_pct
        max_discount_pct = min(max_discount_pct, absolute_max)
        max_discount_pct = max(max_discount_pct, 0.0)
    else:
        max_discount_pct = 0.0

    # Safe discount room: the comfortable zone (80% of max)
    safe_discount_room = max_discount_pct * 0.80

    # Margin health classification
    margin_health = _classify_margin_health(current_margin, margin_floor)

    return {
        "product_id": product_id,
        "title": title,
        "price": round(price, 2),
        "cogs": round(cogs, 2),
        "current_margin": round(current_margin, 4),
        "max_discount_pct": round(max_discount_pct, 4),
        "margin_floor": round(margin_floor, 4),
        "safe_discount_room": round(safe_discount_room, 4),
        "margin_health": margin_health,
    }


def _classify_margin_health(current_margin: float, margin_floor: float) -> str:
    """Classify the health of the current margin."""
    if current_margin <= 0:
        return "critical"
    if current_margin < margin_floor:
        return "critical"
    if current_margin < margin_floor * 1.5:
        return "thin"
    if current_margin < margin_floor * 3.0:
        return "healthy"
    return "excellent"


def _compute_summary(
    analyses: list[dict[str, Any]],
    margin_floor: float,
) -> dict[str, Any]:
    """Compute aggregate margin summary across all products."""
    if not analyses:
        return {
            "avg_margin": 0.0,
            "avg_safe_discount_room": 0.0,
            "min_margin": 0.0,
            "products_discountable": 0,
            "products_total": 0,
            "margin_floor": margin_floor,
        }

    margins = [a["current_margin"] for a in analyses]
    rooms = [a["safe_discount_room"] for a in analyses]
    discountable = sum(1 for a in analyses if a["max_discount_pct"] > 0.01)

    return {
        "avg_margin": round(sum(margins) / len(margins), 4),
        "avg_safe_discount_room": round(sum(rooms) / len(rooms), 4),
        "min_margin": round(min(margins), 4),
        "products_discountable": discountable,
        "products_total": len(analyses),
        "margin_floor": round(margin_floor, 4),
    }
