"""Cost negotiation planner — build a negotiation plan for supplier pricing.

Takes a supplier quote and product details, then produces a full negotiation
plan including target price, leverage points, cost breakdown analysis,
volume discount tiers, and total landed cost.

Input contract:  {status, data: {retail_price, desired_margin_pct, quoted_price,
                  order_quantity, product_type, shipping_method, weight_kg,
                  hs_category, supplier_data}, meta, error}
Output contract: {status, data, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .logic import (
    decide_negotiation_strategy,
    calculate_volume_discount,
    evaluate_payment_terms,
    calculate_total_landed_cost,
)
from .data import (
    COST_BREAKDOWNS_BY_TYPE,
    SHIPPING_COST_PER_KG,
    INSURANCE_RATES,
    DUTY_RATES_BY_HS_CATEGORY,
)
from .rules import validate_order_safeguards


def plan_negotiation(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Main entry point — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))

    # Core calculations
    target_price = _calculate_target_price(
        data.get("retail_price", 0),
        data.get("desired_margin_pct", 60),
    )
    leverage = _identify_leverage_points(data)
    breakdown = _analyze_cost_breakdown(
        data.get("quoted_price", target_price),
        data.get("product_type", "general"),
    )
    volume_tiers = calculate_volume_discount(
        data.get("quoted_price", target_price),
        [100, 250, 500, 1000, 2500, 5000],
    )
    shipping_method = data.get("shipping_method", "sea_standard")
    weight_kg = data.get("weight_kg", 1.0)
    hs_category = data.get("hs_category", "general_goods")
    unit_cost = data.get("quoted_price", target_price)
    shipping_per_unit = SHIPPING_COST_PER_KG.get(shipping_method, 3.0) * weight_kg
    duty_rate = DUTY_RATES_BY_HS_CATEGORY.get(hs_category, 0.05)
    duties_per_unit = round(unit_cost * duty_rate, 2)
    insurance_per_unit = round(unit_cost * INSURANCE_RATES.get("standard", 0.015), 2)

    landed_cost = calculate_total_landed_cost(
        unit_cost, shipping_per_unit, duties_per_unit, insurance_per_unit,
    )
    strategy = decide_negotiation_strategy(
        data.get("supplier_data", {}), target_price,
    )
    safeguards = validate_order_safeguards(data)

    return {
        "status": "success",
        "data": {
            "target_price": target_price,
            "quoted_price": unit_cost,
            "price_gap": round(unit_cost - target_price, 2),
            "leverage_points": leverage,
            "cost_breakdown": breakdown,
            "volume_discount_tiers": volume_tiers,
            "total_landed_cost": landed_cost,
            "recommended_strategy": strategy,
            "order_safeguards": safeguards,
        },
        "meta": {
            "engine": "cost_negotiation",
            "confidence": _compute_confidence(data),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return {"valid": False, "reason": "Invalid input structure"}
    data = payload["data"]
    if not (data.get("retail_price") or data.get("quoted_price")):
        return {"valid": False, "reason": "Need retail_price or quoted_price"}
    return {"valid": True, "reason": "OK"}


def _calculate_target_price(retail_price: float, desired_margin_pct: float) -> float:
    """Target unit cost = retail * (1 - margin). Margin includes all costs."""
    margin = max(0.1, min(0.9, desired_margin_pct / 100))
    return round(retail_price * (1 - margin), 2)


def _identify_leverage_points(data: dict[str, Any]) -> list[dict[str, str]]:
    points = []
    qty = data.get("order_quantity", 0)
    if qty >= 500:
        points.append({"type": "volume", "detail": f"Order of {qty} units justifies bulk discount request"})
    if qty >= 1000:
        points.append({"type": "volume", "detail": "Large order — request 15-25% below list price"})
    points.append({"type": "payment_terms", "detail": "Offer faster payment in exchange for lower price"})
    points.append({"type": "exclusivity", "detail": "Offer exclusivity in your market for better pricing"})
    if data.get("supplier_data", {}).get("competitor_count", 0) > 3:
        points.append({"type": "competition", "detail": "Multiple suppliers available — use competitive quotes"})
    points.append({"type": "repeat_business", "detail": "Signal long-term partnership for volume commitment pricing"})
    return points


def _analyze_cost_breakdown(quoted_price: float, product_type: str) -> dict[str, float]:
    ratios = COST_BREAKDOWNS_BY_TYPE.get(product_type, COST_BREAKDOWNS_BY_TYPE["general"])
    return {
        "material": round(quoted_price * ratios["material"], 2),
        "labor": round(quoted_price * ratios["labor"], 2),
        "overhead": round(quoted_price * ratios["overhead"], 2),
        "profit": round(quoted_price * ratios["profit"], 2),
        "total": quoted_price,
    }


def _compute_confidence(data: dict[str, Any]) -> float:
    score = 0.5
    if data.get("quoted_price"):
        score += 0.15
    if data.get("retail_price"):
        score += 0.1
    if data.get("supplier_data"):
        score += 0.1
    if data.get("product_type") and data["product_type"] in COST_BREAKDOWNS_BY_TYPE:
        score += 0.1
    return min(0.95, round(score, 2))


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "cost_negotiation",
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
