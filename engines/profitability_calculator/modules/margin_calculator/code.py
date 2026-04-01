"""Margin calculation engine — gross, contribution, net, operating, EBITDA.

Main entry point: calculate_margins(input_payload)
Returns engine contract: {status, data, meta, error}

Formulas:
  Gross margin       = (price - COGS) / price x 100
  Contribution margin = (price - ALL variable costs) / price x 100
  Operating margin   = (price - variable costs - ad spend - operating costs) / price x 100
  Net margin         = (price - ALL costs including fixed) / price x 100
  EBITDA margin      = net margin + depreciation/amortization (simplified)
"""
from __future__ import annotations

import time
from typing import Any

from .data import get_category_benchmark, get_tier
from .rules import evaluate_rules
from .logic import assess_margin_health


def calculate_margins(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate all margin types for a product.

    Args:
        input_payload: {
            price: float              — selling price per unit
            cogs: float               — cost of goods sold per unit (landed)
            category: str             — product category (for benchmarks)
            # Variable costs (per unit)
            shipping_cost: float      — shipping/fulfillment per unit (default 0)
            transaction_fees: float   — payment processing per unit (default: 2.9% + $0.30)
            packaging_cost: float     — packaging per unit (default 0)
            other_variable: float     — any other per-unit variable costs (default 0)
            # Period costs (monthly)
            ad_spend_monthly: float   — monthly advertising spend (default 0)
            operating_costs_monthly: float — rent, software, salaries, etc. (default 0)
            fixed_costs_monthly: float — other fixed monthly costs (default 0)
            # Volume
            monthly_units: int        — units sold per month (default 100)
            # Optional
            return_rate: float        — return rate as decimal 0-1 (default 0.05)
            depreciation_monthly: float — depreciation/amortization (default 0)
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    start = time.time()

    try:
        parsed = _parse_input(input_payload)
        margins = _compute_margins(parsed)
        breakdown = _build_breakdown(parsed, margins)
        tier = get_tier(margins["contribution_margin_pct"])
        benchmark = get_category_benchmark(parsed["category"])
        benchmark_comparison = _compare_to_benchmark(margins, benchmark)
        health = assess_margin_health({**margins, "category": parsed["category"]})
        rules_result = evaluate_rules({**margins, "category": parsed["category"]})

        data = {
            "margins": margins,
            "tier": {
                "name": tier["tier"],
                "label": tier["label"],
                "description": tier["description"],
            },
            "breakdown": breakdown,
            "benchmark_comparison": benchmark_comparison,
            "health": health,
            "rules": rules_result,
        }

        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "margin_calculator",
                "duration_ms": round((time.time() - start) * 1000, 2),
                "category": parsed["category"],
                "price": parsed["price"],
                "monthly_units": parsed["monthly_units"],
            },
            "error": None,
        }

    except (ValueError, KeyError, TypeError) as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "module": "margin_calculator",
                "duration_ms": round((time.time() - start) * 1000, 2),
            },
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def _parse_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize input payload."""
    price = float(payload.get("price", 0))
    cogs = float(payload.get("cogs", 0))

    if price <= 0:
        raise ValueError("Price must be greater than zero.")
    if cogs < 0:
        raise ValueError("COGS cannot be negative.")
    if cogs >= price:
        raise ValueError(f"COGS (${cogs:.2f}) >= price (${price:.2f}). Product sells at a loss before any other costs.")

    # Default transaction fee: Shopify Payments 2.9% + $0.30
    default_txn_fee = round(price * 0.029 + 0.30, 2)

    monthly_units = max(1, int(payload.get("monthly_units", 100)))

    return {
        "price": price,
        "cogs": cogs,
        "category": str(payload.get("category", "general")),
        "shipping_cost": float(payload.get("shipping_cost", 0)),
        "transaction_fees": float(payload.get("transaction_fees", default_txn_fee)),
        "packaging_cost": float(payload.get("packaging_cost", 0)),
        "other_variable": float(payload.get("other_variable", 0)),
        "ad_spend_monthly": float(payload.get("ad_spend_monthly", 0)),
        "operating_costs_monthly": float(payload.get("operating_costs_monthly", 0)),
        "fixed_costs_monthly": float(payload.get("fixed_costs_monthly", 0)),
        "monthly_units": monthly_units,
        "return_rate": min(1.0, max(0.0, float(payload.get("return_rate", 0.05)))),
        "depreciation_monthly": float(payload.get("depreciation_monthly", 0)),
    }


def _compute_margins(p: dict[str, Any]) -> dict[str, float]:
    """Core margin math. All values are per-unit then converted to percentages."""
    price = p["price"]
    cogs = p["cogs"]
    units = p["monthly_units"]

    # Per-unit variable costs
    variable_per_unit = (
        p["shipping_cost"]
        + p["transaction_fees"]
        + p["packaging_cost"]
        + p["other_variable"]
    )

    # Per-unit fixed/period costs
    ad_spend_per_unit = p["ad_spend_monthly"] / units
    operating_per_unit = p["operating_costs_monthly"] / units
    fixed_per_unit = p["fixed_costs_monthly"] / units
    depreciation_per_unit = p["depreciation_monthly"] / units

    # Return cost adjustment: returns cost COGS + shipping both ways
    return_cost_per_unit = p["return_rate"] * (cogs + p["shipping_cost"] * 2)

    # --- Margin calculations ---
    gross_profit = price - cogs
    gross_margin_pct = gross_profit / price * 100

    contribution_profit = price - cogs - variable_per_unit - return_cost_per_unit
    contribution_margin_pct = contribution_profit / price * 100

    operating_profit = contribution_profit - ad_spend_per_unit - operating_per_unit
    operating_margin_pct = operating_profit / price * 100

    net_profit = operating_profit - fixed_per_unit
    net_margin_pct = net_profit / price * 100

    ebitda = net_profit + depreciation_per_unit
    ebitda_margin_pct = ebitda / price * 100

    ad_spend_pct = p["ad_spend_monthly"] / (price * units) * 100 if units > 0 else 0

    return {
        "gross_margin_pct": round(gross_margin_pct, 2),
        "gross_profit_per_unit": round(gross_profit, 2),
        "contribution_margin_pct": round(contribution_margin_pct, 2),
        "contribution_profit_per_unit": round(contribution_profit, 2),
        "operating_margin_pct": round(operating_margin_pct, 2),
        "operating_profit_per_unit": round(operating_profit, 2),
        "net_margin_pct": round(net_margin_pct, 2),
        "net_profit_per_unit": round(net_profit, 2),
        "ebitda_margin_pct": round(ebitda_margin_pct, 2),
        "ebitda_per_unit": round(ebitda, 2),
        "ad_spend_pct_of_revenue": round(ad_spend_pct, 2),
        "price": price,
        "cogs": cogs,
        "variable_costs_per_unit": round(variable_per_unit, 2),
        "fixed_costs_monthly": p["fixed_costs_monthly"],
    }


def _build_breakdown(p: dict[str, Any], margins: dict[str, float]) -> dict[str, Any]:
    """Build detailed cost and margin breakdown."""
    price = p["price"]
    units = p["monthly_units"]

    return {
        "per_unit": {
            "selling_price": price,
            "cogs": p["cogs"],
            "shipping": p["shipping_cost"],
            "transaction_fees": p["transaction_fees"],
            "packaging": p["packaging_cost"],
            "other_variable": p["other_variable"],
            "return_cost_allocated": round(p["return_rate"] * (p["cogs"] + p["shipping_cost"] * 2), 2),
            "ad_spend_allocated": round(p["ad_spend_monthly"] / units, 2),
            "operating_allocated": round(p["operating_costs_monthly"] / units, 2),
            "fixed_allocated": round(p["fixed_costs_monthly"] / units, 2),
        },
        "monthly": {
            "revenue": round(price * units, 2),
            "total_cogs": round(p["cogs"] * units, 2),
            "total_variable": round(margins["variable_costs_per_unit"] * units, 2),
            "ad_spend": p["ad_spend_monthly"],
            "operating_costs": p["operating_costs_monthly"],
            "fixed_costs": p["fixed_costs_monthly"],
            "gross_profit": round(margins["gross_profit_per_unit"] * units, 2),
            "contribution_profit": round(margins["contribution_profit_per_unit"] * units, 2),
            "net_profit": round(margins["net_profit_per_unit"] * units, 2),
        },
    }


def _compare_to_benchmark(margins: dict[str, float], benchmark: dict[str, float]) -> dict[str, Any]:
    """Compare calculated margins to category benchmarks."""
    comparisons = {}
    for margin_type in ["gross", "contribution", "net", "operating"]:
        actual = margins.get(f"{margin_type}_margin_pct", 0)
        bench = benchmark.get(margin_type, 0)
        diff = actual - bench
        if diff >= 5:
            status = "above_benchmark"
        elif diff >= -5:
            status = "at_benchmark"
        else:
            status = "below_benchmark"

        comparisons[margin_type] = {
            "actual_pct": actual,
            "benchmark_pct": bench,
            "difference": round(diff, 2),
            "status": status,
        }

    return comparisons
