"""Seasonal Risk assessment — demand volatility, cash flow gaps, inventory timing.

Main entry point: assess_seasonal_risk(input_payload)
Engine contract: returns {status, data, meta, error}
"""
from __future__ import annotations
import time
from typing import Any
from .data import get_category_seasonality, get_weather_impact, MONTHLY_DEMAND_INDEX
from .logic import calculate_cash_reserve_needed, assess_fad_risk, recommend_seasonal_strategy
from .rules import evaluate_rules


def assess_seasonal_risk(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Run full seasonal risk assessment for a product or category."""
    start = time.time()
    try:
        data = input_payload.get("data") or input_payload
        category = data.get("category", data.get("product_type", "general"))
        launch_month = data.get("launch_month")
        cash_reserve_months = data.get("cash_reserve_months", 0)
        inventory_months = data.get("inventory_months_on_hand", 0)
        weather_dep = data.get("weather_dependent", False)

        profile = get_category_seasonality(category)
        ptr = profile["peak_to_trough_ratio"]
        classification = profile["classification"]

        # Override classification if fad signals detected
        trend_data = data.get("trend_data", {})
        fad_result = assess_fad_risk(trend_data) if trend_data else None
        if fad_result and fad_result["is_fad"]:
            classification = "fad"

        # Score each risk dimension (0-1 scale)
        scores = {
            "revenue_volatility": _score_volatility(ptr),
            "cash_reserve_adequacy": _score_cash_adequacy(classification, cash_reserve_months),
            "inventory_timing": _score_inventory_timing(launch_month, profile["peak_months"], inventory_months, classification),
            "fad_risk": fad_result["fad_score"] if fad_result else 0.0,
            "weather_dependency": _score_weather(category, weather_dep),
        }
        weights = {"revenue_volatility": 0.30, "cash_reserve_adequacy": 0.25, "inventory_timing": 0.20, "fad_risk": 0.15, "weather_dependency": 0.10}
        composite = sum(scores[k] * weights[k] for k in scores)
        risk_level = "low" if composite < 0.20 else "moderate" if composite < 0.40 else "high" if composite < 0.65 else "extreme"

        mf, mv = data.get("monthly_fixed_costs", 5000.0), data.get("monthly_variable_costs", 3000.0)
        rules_ctx = {"classification": classification, "cash_reserve_months": cash_reserve_months,
                      "inventory_months_on_hand": inventory_months, "launch_month": launch_month,
                      "peak_months": profile["peak_months"], "trough_months": profile["trough_months"],
                      "weather_dependent": weather_dep, "has_weather_contingency": data.get("has_weather_contingency", False),
                      "trend_duration_months": trend_data.get("trend_duration_months", 0)}

        return {
            "status": "success",
            "data": {
                "classification": classification, "risk_level": risk_level,
                "composite_risk_score": round(composite, 3),
                "risk_dimensions": {k: round(v, 3) for k, v in scores.items()},
                "seasonality_profile": profile,
                "cash_reserve_analysis": calculate_cash_reserve_needed(profile, mf, mv),
                "fad_assessment": fad_result,
                "monthly_cash_flow_projection": _project_cash_flow(profile, mf, mv, data.get("expected_monthly_revenue", 10000.0)),
                "strategy": recommend_seasonal_strategy(risk_level, classification, profile["peak_months"]),
                "rules_evaluation": evaluate_rules(rules_ctx),
            },
            "meta": {"module": "seasonal_risk", "category": category, "elapsed_seconds": round(time.time() - start, 4)},
            "error": None,
        }
    except Exception as exc:
        return {"status": "error", "data": None, "meta": {"module": "seasonal_risk", "elapsed_seconds": round(time.time() - start, 4)}, "error": str(exc)}


def _score_volatility(ptr: float) -> float:
    if ptr <= 1.5: return 0.10
    if ptr <= 3.0: return 0.35
    if ptr <= 5.0: return 0.60
    return min(0.50 + (ptr - 5.0) * 0.05, 1.0)


def _score_cash_adequacy(classification: str, reserve: float) -> float:
    needed = {"non_seasonal": 2, "moderate_seasonal": 3, "highly_seasonal": 4, "fad": 1}.get(classification, 2)
    if reserve >= needed: return 0.10
    if reserve >= needed * 0.5: return 0.50
    return 0.90


def _score_inventory_timing(launch: int | None, peaks: list[int], inv: float, cls: str) -> float:
    score = 0.0
    if cls == "fad" and inv > 2: score += 0.50
    if cls == "highly_seasonal" and inv > 4: score += 0.30
    if launch and peaks:
        min_dist = min((p - launch) % 12 for p in peaks)
        if min_dist > 6: score += 0.40
        elif min_dist > 3: score += 0.20
    return min(score, 1.0)


def _score_weather(category: str, dependent: bool) -> float:
    if not dependent: return 0.05
    impacts = [abs(get_weather_impact(category, e)) for e in ("rain", "heat_wave", "cold_snap", "snow")]
    return min(0.30 + max(impacts), 1.0)


def _project_cash_flow(profile: dict, fixed: float, variable: float, avg_rev: float) -> list[dict]:
    peaks, troughs = set(profile.get("peak_months", [])), set(profile.get("trough_months", []))
    ptr = profile.get("peak_to_trough_ratio", 1.0)
    result = []
    for i in range(12):
        m = i + 1
        df = MONTHLY_DEMAND_INDEX[i]
        if m in peaks: df *= (ptr / 2.0)
        elif m in troughs: df *= (1.0 / ptr)
        rev, cost = avg_rev * df, fixed + variable * df
        period = "peak" if m in peaks else "trough" if m in troughs else "normal"
        result.append({"month": m, "estimated_revenue": round(rev, 2), "estimated_costs": round(cost, 2), "net_cash_flow": round(rev - cost, 2), "period": period})
    return result
