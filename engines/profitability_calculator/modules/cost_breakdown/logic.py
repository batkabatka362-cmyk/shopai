"""Decision functions for cost optimization and comparison.

These functions operate on cost breakdown results to drive business decisions:
where to cut costs, which products have better economics, and minimum pricing.
"""

from __future__ import annotations

from typing import Any

from .code import calculate_cost_breakdown
from .rules import COST_RULES


def identify_cost_reduction_opportunities(
    breakdown: dict[str, Any],
) -> dict[str, Any]:
    """Analyze a cost breakdown and identify actionable cost reduction opportunities.

    Args:
        breakdown: the 'data' dict from calculate_cost_breakdown result.

    Returns:
        Engine contract {status, data, meta, error}.
    """
    if not breakdown or "breakdown" not in breakdown:
        return _error("Invalid breakdown — pass the 'data' field from calculate_cost_breakdown")

    selling_price = breakdown["selling_price"]
    categories = {item["category"]: item for item in breakdown["breakdown"]}
    opportunities: list[dict[str, Any]] = []

    # --- COGS reduction ---
    cogs_item = categories.get("cogs", {})
    cogs_pct = cogs_item.get("percent_of_price", 0)
    if cogs_pct > 0.35:
        savings_if_reduced = round(cogs_item["amount_usd"] * 0.10, 2)  # 10% supplier negotiation
        opportunities.append({
            "category": "cogs",
            "current_pct": cogs_pct,
            "target_pct": 0.30,
            "strategy": "Negotiate 10% supplier discount at higher MOQ or find alternative supplier",
            "potential_savings_per_unit": savings_if_reduced,
            "difficulty": "medium",
            "priority": 1,
        })

    # --- Shipping optimization ---
    shipping_item = categories.get("shipping_cost", {})
    shipping_pct = shipping_item.get("percent_of_price", 0)
    if shipping_pct > 0.10:
        current_cost = shipping_item["amount_usd"]
        target_cost = selling_price * 0.08
        opportunities.append({
            "category": "shipping_cost",
            "current_pct": shipping_pct,
            "target_pct": 0.08,
            "strategy": (
                "Negotiate volume carrier rates, reduce package weight/dimensions, "
                "use regional carriers, or consolidate shipments"
            ),
            "potential_savings_per_unit": round(max(current_cost - target_cost, 0), 2),
            "difficulty": "medium",
            "priority": 2,
        })

    # --- Packaging bulk ordering ---
    packaging_item = categories.get("packaging_cost", {})
    packaging_pct = packaging_item.get("percent_of_price", 0)
    if packaging_pct > 0.03:
        current_cost = packaging_item["amount_usd"]
        # Assume moving to 1000+ qty = 50% reduction
        opportunities.append({
            "category": "packaging_cost",
            "current_pct": packaging_pct,
            "target_pct": round(packaging_pct * 0.50, 4),
            "strategy": "Order packaging at 1000+ quantity for 50% discount; simplify design",
            "potential_savings_per_unit": round(current_cost * 0.50, 2),
            "difficulty": "easy",
            "priority": 3,
        })

    # --- Ad spend efficiency ---
    ads_item = categories.get("ad_cost_per_unit", {})
    ads_pct = ads_item.get("percent_of_price", 0)
    if ads_pct > 0.15:
        current_cost = ads_item["amount_usd"]
        target_cost = selling_price * 0.12
        opportunities.append({
            "category": "ad_cost_per_unit",
            "current_pct": ads_pct,
            "target_pct": 0.12,
            "strategy": (
                "Improve ROAS: tighten audience targeting, A/B test creatives, "
                "invest in organic/SEO, build email list for repeat sales"
            ),
            "potential_savings_per_unit": round(max(current_cost - target_cost, 0), 2),
            "difficulty": "hard",
            "priority": 2,
        })

    # --- Returns reduction ---
    returns_item = categories.get("return_refund_cost", {})
    returns_pct = returns_item.get("percent_of_price", 0)
    if returns_pct > 0.05:
        current_cost = returns_item["amount_usd"]
        opportunities.append({
            "category": "return_refund_cost",
            "current_pct": returns_pct,
            "target_pct": 0.03,
            "strategy": (
                "Improve product descriptions and photos, add size guides, "
                "implement quality control, offer exchanges instead of refunds"
            ),
            "potential_savings_per_unit": round(current_cost * 0.40, 2),
            "difficulty": "medium",
            "priority": 2,
        })

    # --- Warehousing optimization ---
    warehouse_item = categories.get("warehousing_cost", {})
    warehouse_pct = warehouse_item.get("percent_of_price", 0)
    if warehouse_pct > 0.06:
        current_cost = warehouse_item["amount_usd"]
        opportunities.append({
            "category": "warehousing_cost",
            "current_pct": warehouse_pct,
            "target_pct": 0.04,
            "strategy": "Improve inventory turnover, reduce safety stock, compare 3PL providers",
            "potential_savings_per_unit": round(current_cost * 0.30, 2),
            "difficulty": "medium",
            "priority": 4,
        })

    # --- Sort by potential savings descending ---
    opportunities.sort(key=lambda x: x["potential_savings_per_unit"], reverse=True)

    total_potential_savings = round(
        sum(o["potential_savings_per_unit"] for o in opportunities), 2
    )
    new_margin = round(
        breakdown["margin_percent"] + (total_potential_savings / selling_price), 4
    )

    return {
        "status": "success",
        "data": {
            "opportunities": opportunities,
            "total_potential_savings_per_unit": total_potential_savings,
            "current_margin": breakdown["margin_percent"],
            "projected_margin_after_savings": min(new_margin, 1.0),
            "top_opportunity": opportunities[0] if opportunities else None,
        },
        "meta": {
            "opportunities_found": len(opportunities),
            "selling_price": selling_price,
        },
        "error": None,
    }


def compare_cost_structures(
    product_a: dict[str, Any], product_b: dict[str, Any]
) -> dict[str, Any]:
    """Compare cost structures of two products to determine which has better economics.

    Args:
        product_a: input_payload for product A (passed to calculate_cost_breakdown).
        product_b: input_payload for product B.

    Returns:
        Engine contract with comparative analysis.
    """
    result_a = calculate_cost_breakdown(product_a)
    result_b = calculate_cost_breakdown(product_b)

    if result_a["status"] == "error":
        return _error(f"Product A calculation failed: {result_a['error']}")
    if result_b["status"] == "error":
        return _error(f"Product B calculation failed: {result_b['error']}")

    data_a = result_a["data"]
    data_b = result_b["data"]

    # Build per-category comparison
    cats_a = {item["category"]: item for item in data_a["breakdown"]}
    cats_b = {item["category"]: item for item in data_b["breakdown"]}
    all_categories = set(cats_a.keys()) | set(cats_b.keys())

    comparison: list[dict[str, Any]] = []
    for cat in sorted(all_categories):
        a_pct = cats_a.get(cat, {}).get("percent_of_price", 0)
        b_pct = cats_b.get(cat, {}).get("percent_of_price", 0)
        a_amt = cats_a.get(cat, {}).get("amount_usd", 0)
        b_amt = cats_b.get(cat, {}).get("amount_usd", 0)
        comparison.append({
            "category": cat,
            "product_a_usd": a_amt,
            "product_a_pct": a_pct,
            "product_b_usd": b_amt,
            "product_b_pct": b_pct,
            "winner": "A" if a_pct < b_pct else ("B" if b_pct < a_pct else "tie"),
        })

    winner = (
        "A" if data_a["margin_percent"] > data_b["margin_percent"]
        else ("B" if data_b["margin_percent"] > data_a["margin_percent"] else "tie")
    )

    margin_gap = round(abs(data_a["margin_percent"] - data_b["margin_percent"]), 4)

    return {
        "status": "success",
        "data": {
            "winner": winner,
            "margin_gap": margin_gap,
            "product_a": {
                "selling_price": data_a["selling_price"],
                "total_cost": data_a["total_cost_per_unit"],
                "margin_percent": data_a["margin_percent"],
                "biggest_cost_driver": data_a["biggest_cost_driver"]["category"],
            },
            "product_b": {
                "selling_price": data_b["selling_price"],
                "total_cost": data_b["total_cost_per_unit"],
                "margin_percent": data_b["margin_percent"],
                "biggest_cost_driver": data_b["biggest_cost_driver"]["category"],
            },
            "category_comparison": comparison,
        },
        "meta": {"comparison_type": "full_cost_structure"},
        "error": None,
    }


def calculate_minimum_viable_price(
    costs: dict[str, Any], target_margin: float = 0.30
) -> dict[str, Any]:
    """Calculate the lowest price to achieve a target margin.

    Uses iterative approach because payment fees and insurance are
    price-dependent — the minimum price is a function of itself.

    Args:
        costs: input_payload for calculate_cost_breakdown (without selling_price).
        target_margin: desired margin as decimal (default 0.30 = 30%).

    Returns:
        Engine contract with minimum viable price and breakdown at that price.
    """
    if target_margin <= 0 or target_margin >= 1:
        return _error("target_margin must be between 0 and 1 (exclusive)")

    # Start with a rough estimate: price = total_fixed_costs / (1 - margin - variable_rate)
    cogs = costs.get("cogs", 0)
    if cogs <= 0:
        return _error("cogs is required and must be positive")

    # Initial guess: COGS / (1 - target_margin) * 2 to overshoot
    price_guess = cogs / (1 - target_margin) * 1.5

    # Iterate to converge (payment fee and insurance depend on price)
    for iteration in range(20):
        test_payload = {**costs, "selling_price": round(price_guess, 2)}
        result = calculate_cost_breakdown(test_payload)

        if result["status"] == "error":
            return _error(f"Iteration {iteration} failed: {result['error']}")

        total_cost = result["data"]["total_cost_per_unit"]
        # Required price = total_cost / (1 - target_margin)
        required_price = total_cost / (1 - target_margin)

        # Check convergence
        if abs(required_price - price_guess) < 0.01:
            price_guess = required_price
            break

        price_guess = required_price

    final_price = round(price_guess, 2)

    # Get final breakdown at converged price
    final_payload = {**costs, "selling_price": final_price}
    final_result = calculate_cost_breakdown(final_payload)

    if final_result["status"] == "error":
        return _error(f"Final calculation failed: {final_result['error']}")

    return {
        "status": "success",
        "data": {
            "minimum_viable_price": final_price,
            "target_margin": target_margin,
            "actual_margin": final_result["data"]["margin_percent"],
            "total_cost_at_mvp": final_result["data"]["total_cost_per_unit"],
            "profit_per_unit_at_mvp": final_result["data"]["profit_per_unit"],
            "breakdown_at_mvp": final_result["data"]["breakdown"],
            "biggest_cost_driver": final_result["data"]["biggest_cost_driver"],
        },
        "meta": {
            "iterations_to_converge": iteration + 1,
            "target_margin": target_margin,
        },
        "error": None,
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
