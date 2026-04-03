"""Operations Agent evaluator — assess quality of operations results.

Evaluates:
  - Stock health (are inventory levels healthy?)
  - Supplier reliability (are suppliers performing well?)
  - Shipping efficiency (are shipments on time and cost-effective?)
  - Forecast accuracy (are predictions reliable?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate operations quality.

    Returns score 0-100 with detailed breakdown.
    """
    engine_results = results.get("engine_results", {})
    completed = results.get("completed_steps", 0)
    total = results.get("total_steps", 1)

    scores: dict[str, float] = {}
    issues: list[str] = []
    strengths: list[str] = []

    # 1. Stock health (0-25): Are inventory levels healthy?
    stock_health = _score_stock_health(engine_results)
    scores["stock_health"] = stock_health
    if stock_health >= 20:
        strengths.append("Inventory levels are healthy with minimal stockout risk")
    elif stock_health < 10:
        issues.append("Critical inventory issues — stockout risks detected")

    # 2. Supplier reliability (0-25): Are suppliers performing?
    supplier_reliability = _score_supplier_reliability(engine_results)
    scores["supplier_reliability"] = supplier_reliability
    if supplier_reliability >= 20:
        strengths.append("Supplier performance is strong and reliable")
    elif supplier_reliability < 10:
        issues.append("Supplier reliability concerns — consider backup suppliers")

    # 3. Shipping efficiency (0-25): Are shipments optimized?
    shipping_efficiency = _score_shipping_efficiency(engine_results)
    scores["shipping_efficiency"] = shipping_efficiency
    if shipping_efficiency >= 20:
        strengths.append("Shipping operations are efficient and cost-effective")
    elif shipping_efficiency < 10:
        issues.append("Shipping inefficiencies detected — review carrier strategy")

    # 4. Forecast accuracy (0-25): Are predictions reliable?
    forecast_accuracy = _score_forecast_accuracy(engine_results)
    scores["forecast_accuracy"] = forecast_accuracy
    if forecast_accuracy >= 20:
        strengths.append("Demand forecasting is accurate and actionable")
    elif forecast_accuracy < 10:
        issues.append("Forecast data insufficient — predictions may be unreliable")

    total_score = sum(scores.values())
    total_score = max(0, min(100, round(total_score)))

    quality = "high" if total_score >= 70 else "medium" if total_score >= 40 else "low"

    return {
        "score": total_score,
        "quality": quality,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
        "recommendation": _overall_recommendation(total_score, engine_results),
    }


def _score_stock_health(results: dict[str, Any]) -> float:
    """Score inventory health status."""
    score = 0

    inv = results.get("inventory", {})
    if inv.get("status") == "success":
        inv_data = inv.get("data", {})
        if inv_data.get("inventory_health"):
            score += 8
        if inv_data.get("reorder_plan"):
            score += 7
        if inv_data.get("stockout_risks") is not None:
            risks = inv_data["stockout_risks"]
            if isinstance(risks, list) and len(risks) == 0:
                score += 10
            elif isinstance(risks, list) and len(risks) <= 3:
                score += 5
            else:
                score += 2

    return min(25, score)


def _score_supplier_reliability(results: dict[str, Any]) -> float:
    """Score supplier performance."""
    score = 0

    sup = results.get("supplier", {})
    if sup.get("status") == "success":
        sup_data = sup.get("data", {})
        if sup_data.get("supplier_scores"):
            score += 12
            supplier_scores = sup_data["supplier_scores"]
            if isinstance(supplier_scores, list) and len(supplier_scores) > 0:
                score += 5

    sd = results.get("supplier_discovery", {})
    if sd.get("status") == "success":
        sd_data = sd.get("data", {})
        if sd_data.get("new_suppliers"):
            score += 8

    return min(25, score)


def _score_shipping_efficiency(results: dict[str, Any]) -> float:
    """Score shipping optimization quality."""
    score = 0

    ship = results.get("shipping_optimization", {})
    if ship.get("status") == "success":
        ship_data = ship.get("data", {})
        if ship_data.get("shipping_plan"):
            score += 15
            plan = ship_data["shipping_plan"]
            if isinstance(plan, dict) and plan.get("optimized"):
                score += 10

    return min(25, score)


def _score_forecast_accuracy(results: dict[str, Any]) -> float:
    """Score stock forecast quality."""
    score = 0

    sp = results.get("stock_prediction", {})
    if sp.get("status") == "success":
        sp_data = sp.get("data", {})
        if sp_data.get("stock_forecast"):
            score += 15
            forecast = sp_data["stock_forecast"]
            if isinstance(forecast, dict) and forecast.get("confidence"):
                confidence = forecast["confidence"]
                if confidence >= 0.8:
                    score += 10
                elif confidence >= 0.5:
                    score += 5

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    inv = results.get("inventory", {})
    has_stockout_risks = False
    if inv.get("status") == "success":
        risks = inv.get("data", {}).get("stockout_risks", [])
        has_stockout_risks = isinstance(risks, list) and len(risks) > 0

    if score >= 70:
        if has_stockout_risks:
            return "Operations are generally healthy but reorder actions needed for at-risk items."
        return "Operations are running smoothly. Continue monitoring and optimizing."

    if score >= 40:
        return "Operations show mixed signals. Review supplier reliability and inventory levels."

    return "Operations need attention. Recommend immediate inventory audit and supplier review."
