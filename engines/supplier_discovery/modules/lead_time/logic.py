"""Lead time decision logic — shipping selection, reorder, and risk assessment.

These functions encapsulate the judgment calls that come from experience:
when to use air vs sea, how much safety stock to hold, and whether a
supplier's delivery pattern signals trouble.
"""
from __future__ import annotations

import math
from typing import Any

from .data import SHIPPING_TIMES, CARRIER_RELIABILITY


# Weight thresholds (kg) where shipping economics shift
_SEA_THRESHOLD_KG = 100
_AIR_THRESHOLD_KG = 30

# Service-level Z-scores
_Z_SCORES = {0.90: 1.28, 0.95: 1.65, 0.99: 2.33}


def choose_shipping_method(
    urgency: str,
    cost_sensitivity: str,
    weight_kg: float,
) -> dict[str, Any]:
    """Decide between sea, air, and express shipping.

    Args:
        urgency: "low" / "medium" / "high" / "critical"
        cost_sensitivity: "low" / "medium" / "high"
        weight_kg: shipment weight in kilograms

    Returns dict with recommended method, reasoning, and estimated cost tier.
    """
    # Score each method 0-10 based on inputs
    scores = {"sea": 0, "air": 0, "express": 0}

    # Urgency scoring
    urgency_map = {
        "low":      {"sea": 10, "air": 4, "express": 1},
        "medium":   {"sea": 5,  "air": 8, "express": 5},
        "high":     {"sea": 1,  "air": 7, "express": 9},
        "critical": {"sea": 0,  "air": 3, "express": 10},
    }
    for method, pts in urgency_map.get(urgency, urgency_map["medium"]).items():
        scores[method] += pts

    # Cost sensitivity scoring
    cost_map = {
        "low":    {"sea": 3, "air": 7, "express": 10},
        "medium": {"sea": 6, "air": 7, "express": 4},
        "high":   {"sea": 10, "air": 4, "express": 1},
    }
    for method, pts in cost_map.get(cost_sensitivity, cost_map["medium"]).items():
        scores[method] += pts

    # Weight scoring — heavy shipments strongly favor sea
    if weight_kg >= _SEA_THRESHOLD_KG:
        scores["sea"] += 8
        scores["air"] += 3
        scores["express"] += 1
    elif weight_kg >= _AIR_THRESHOLD_KG:
        scores["sea"] += 5
        scores["air"] += 7
        scores["express"] += 3
    else:
        scores["sea"] += 2
        scores["air"] += 6
        scores["express"] += 8

    best = max(scores, key=scores.get)  # type: ignore[arg-type]

    reasons = {
        "sea": "Lowest cost per kg; best for heavy, non-urgent shipments.",
        "air": "Good balance of speed and cost; handles medium weight well.",
        "express": "Fastest option; ideal for light, urgent shipments.",
    }
    cost_tiers = {"sea": "$0.30-0.80/kg", "air": "$3-6/kg", "express": "$8-25/kg"}

    return {
        "recommended": best,
        "scores": scores,
        "reason": reasons[best],
        "estimated_cost": cost_tiers[best],
        "alternative": sorted(scores, key=scores.get, reverse=True)[1],  # type: ignore[arg-type]
    }


def calculate_reorder_point(
    daily_sales: float,
    total_lead_time_days: float,
    service_level: float = 0.95,
    demand_std_dev: float | None = None,
) -> dict[str, Any]:
    """Calculate reorder point and safety stock.

    Uses the classic ROP formula:
        ROP = (daily_demand * lead_time) + safety_stock
        safety_stock = Z * std_dev_demand * sqrt(lead_time)

    If demand_std_dev is not provided, we estimate it as 30% of daily_sales
    (typical for e-commerce).
    """
    if demand_std_dev is None:
        demand_std_dev = daily_sales * 0.30

    z = _Z_SCORES.get(service_level, 1.65)
    safety_stock = math.ceil(z * demand_std_dev * math.sqrt(total_lead_time_days))
    base_demand = math.ceil(daily_sales * total_lead_time_days)
    rop = base_demand + safety_stock
    days_of_cover = round(rop / max(daily_sales, 0.01), 1)

    return {
        "reorder_point_units": rop,
        "safety_stock_units": safety_stock,
        "base_demand_during_lead": base_demand,
        "days_of_cover": days_of_cover,
        "service_level": service_level,
        "note": (
            f"Reorder when inventory hits {rop} units. "
            f"Safety stock of {safety_stock} units covers demand variability "
            f"at {int(service_level * 100)}% service level."
        ),
    }


def assess_delivery_risk(supplier_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate likelihood a supplier delivers late.

    Expects supplier_data keys:
        quoted_lead_days, actual_deliveries (list of actual days),
        carrier (optional), origin_country (optional)
    """
    quoted = supplier_data.get("quoted_lead_days", 14)
    actuals = supplier_data.get("actual_deliveries", [])
    carrier = supplier_data.get("carrier", "unknown")
    origin = supplier_data.get("origin_country", "CN")

    # Carrier reliability baseline
    carrier_info = CARRIER_RELIABILITY.get(carrier, CARRIER_RELIABILITY.get("unknown", {}))
    carrier_on_time = carrier_info.get("on_time_pct", 0.75)

    if not actuals:
        # No history — rely on carrier data and origin heuristics
        risk_score = round((1 - carrier_on_time) * 100)
        return {
            "risk_score": risk_score,
            "risk_level": _risk_label(risk_score),
            "on_time_rate": None,
            "avg_delay_days": None,
            "carrier_on_time_pct": carrier_on_time,
            "recommendation": "No delivery history. Order samples to build data.",
        }

    on_time = sum(1 for a in actuals if a <= quoted) / len(actuals)
    avg_actual = sum(actuals) / len(actuals)
    avg_delay = round(avg_actual - quoted, 1)
    max_delay = max(actuals) - quoted
    std_dev = (sum((a - avg_actual) ** 2 for a in actuals) / len(actuals)) ** 0.5

    # Risk score: 0 (no risk) to 100 (very risky)
    late_pct_penalty = (1 - on_time) * 50
    delay_penalty = min(30, avg_delay * 3) if avg_delay > 0 else 0
    variance_penalty = min(20, std_dev * 2)
    risk_score = round(min(100, late_pct_penalty + delay_penalty + variance_penalty))

    return {
        "risk_score": risk_score,
        "risk_level": _risk_label(risk_score),
        "on_time_rate": round(on_time, 2),
        "avg_delay_days": avg_delay,
        "max_delay_days": max_delay,
        "std_dev_days": round(std_dev, 1),
        "carrier_on_time_pct": carrier_on_time,
        "recommendation": _risk_recommendation(risk_score, avg_delay, on_time),
    }


def _risk_label(score: int) -> str:
    if score <= 20:
        return "low"
    if score <= 45:
        return "moderate"
    if score <= 70:
        return "high"
    return "critical"


def _risk_recommendation(score: int, avg_delay: float, on_time: float) -> str:
    if score <= 20:
        return "Reliable supplier. Standard buffer is sufficient."
    if score <= 45:
        return f"Moderate risk. Add {max(3, round(avg_delay * 1.5))} days buffer to quoted lead time."
    if score <= 70:
        return "High risk. Consider splitting orders across two suppliers for redundancy."
    return "Critical risk. Find alternative supplier. Current one is unreliable."
