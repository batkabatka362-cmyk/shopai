"""Lead time analysis — total landed time from order to customer door.

Breaks down the full supply chain timeline:
  1. Production time (manufacturing + QC)
  2. Shipping time (sea / air / express)
  3. Customs clearance (varies by country)
  4. Last mile delivery (warehouse to customer)

Lead time variance is modeled because suppliers consistently understate
actual timelines. A supplier quoting 14 days often delivers in 10-28.

Input contract: {status, data: {supplier_location, destination, shipping_method,
    production_days, weight_kg, product_type, daily_sales, service_level}, meta, error}
Output contract: {status, data: {breakdown, total_days, variance, buffers,
    shipping_comparison, reorder_point}, meta, error}
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any

from .data import SHIPPING_TIMES, CUSTOMS_PROCESSING, PEAK_SEASON_DELAYS
from .rules import validate_lead_time, apply_peak_adjustment, MIN_BUFFER_PCT


# Variance multipliers — real-world padding over supplier quotes
VARIANCE_TABLE = {
    "production":  {"optimistic": 0.85, "likely": 1.00, "pessimistic": 1.60},
    "shipping":    {"optimistic": 0.90, "likely": 1.00, "pessimistic": 1.45},
    "customs":     {"optimistic": 0.70, "likely": 1.00, "pessimistic": 2.50},
    "last_mile":   {"optimistic": 0.80, "likely": 1.00, "pessimistic": 1.30},
}

# Z-scores for service-level buffers
SERVICE_LEVEL_Z = {0.90: 1.28, 0.95: 1.65, 0.99: 2.33}


def analyze_lead_time(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Main entry point — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    breakdown = _build_breakdown(data)
    variance = _model_variance(breakdown)
    buffers = _calculate_buffers(variance)
    comparison = _compare_shipping_methods(data)
    total_likely = sum(v["likely"] for v in breakdown.values())

    # Optional reorder point
    daily_sales = data.get("daily_sales", 0)
    service_level = data.get("service_level", 0.95)
    reorder_point = None
    if daily_sales > 0:
        std_dev = variance["std_dev_days"]
        z = SERVICE_LEVEL_Z.get(service_level, 1.65)
        safety_stock = math.ceil(z * std_dev * math.sqrt(daily_sales))
        reorder_point = math.ceil(daily_sales * total_likely) + safety_stock

    return {
        "status": "success",
        "data": {
            "breakdown": breakdown,
            "total_days": {
                "optimistic": sum(v["optimistic"] for v in breakdown.values()),
                "likely": total_likely,
                "pessimistic": sum(v["pessimistic"] for v in breakdown.values()),
            },
            "variance": variance,
            "buffers": buffers,
            "shipping_comparison": comparison,
            "reorder_point": reorder_point,
        },
        "meta": {
            "engine": "lead_time",
            "confidence": 0.75,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return {"valid": False, "reason": "Invalid input structure"}
    return {"valid": True, "reason": "OK"}


def _build_breakdown(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    origin = data.get("supplier_location", "CN")
    dest = data.get("destination", "US")
    method = data.get("shipping_method", "sea")
    production = data.get("production_days", 15)

    route_key = f"{origin}>{dest}"
    ship = SHIPPING_TIMES.get(method, SHIPPING_TIMES["sea"])
    transit = ship.get(route_key, ship.get("default", {"min": 10, "typical": 20, "max": 40}))
    customs = CUSTOMS_PROCESSING.get(dest, CUSTOMS_PROCESSING["default"])
    last_mile = {"min": 2, "typical": 4, "max": 7}

    is_peak = data.get("peak_season", False)

    def _spread(base, stage):
        v = VARIANCE_TABLE[stage]
        opt = round(base * v["optimistic"])
        lik = round(base * v["likely"])
        pes = round(base * v["pessimistic"])
        if is_peak:
            opt, lik, pes = apply_peak_adjustment(opt, lik, pes)
        return {"optimistic": opt, "likely": lik, "pessimistic": pes}

    return {
        "production": _spread(production, "production"),
        "shipping": _spread(transit["typical"], "shipping"),
        "customs": _spread(customs["typical"], "customs"),
        "last_mile": _spread(last_mile["typical"], "last_mile"),
    }


def _model_variance(breakdown: dict) -> dict[str, Any]:
    """PERT-style three-point estimate for standard deviation."""
    total_opt = sum(v["optimistic"] for v in breakdown.values())
    total_lik = sum(v["likely"] for v in breakdown.values())
    total_pes = sum(v["pessimistic"] for v in breakdown.values())
    mean = (total_opt + 4 * total_lik + total_pes) / 6
    std_dev = (total_pes - total_opt) / 6
    return {
        "pert_mean_days": round(mean, 1),
        "std_dev_days": round(std_dev, 1),
        "range": {"min": total_opt, "max": total_pes},
    }


def _calculate_buffers(variance: dict) -> dict[str, int]:
    """Buffer days for each service level."""
    std = variance["std_dev_days"]
    mean = variance["pert_mean_days"]
    buffers = {}
    for level, z in SERVICE_LEVEL_Z.items():
        raw = math.ceil(mean + z * std)
        minimum = math.ceil(mean * (1 + MIN_BUFFER_PCT))
        buffers[f"{int(level * 100)}%"] = max(raw, minimum)
    return buffers


def _compare_shipping_methods(data: dict[str, Any]) -> list[dict[str, Any]]:
    origin = data.get("supplier_location", "CN")
    dest = data.get("destination", "US")
    route_key = f"{origin}>{dest}"
    results = []
    for method, routes in SHIPPING_TIMES.items():
        transit = routes.get(route_key, routes.get("default", {"min": 5, "typical": 15, "max": 30}))
        cost_per_kg = routes.get("cost_per_kg", 0)
        results.append({
            "method": method,
            "transit_days": transit["typical"],
            "range": f"{transit['min']}-{transit['max']} days",
            "cost_per_kg_usd": cost_per_kg,
        })
    results.sort(key=lambda r: r["transit_days"])
    return results


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail", "data": None,
        "meta": {"engine": "lead_time", "confidence": 0,
                 "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
