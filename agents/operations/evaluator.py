"""Operations Agent evaluator — assess quality of operations results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import ScoreComponent, evaluate_results_base


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate operations quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            ScoreComponent(
                name="stock_health",
                scorer=lambda er, meta: _score_stock_health(er),
                strong_text="Inventory levels are healthy with minimal stockout risk",
                weak_text="Inventory health is poor — stockout risks detected",
            ),
            ScoreComponent(
                name="supplier_reliability",
                scorer=lambda er, meta: _score_supplier_reliability(er),
                strong_text="Suppliers are reliable with strong performance scores",
                weak_text="Supplier reliability is low — consider backup suppliers",
            ),
            ScoreComponent(
                name="shipping_efficiency",
                scorer=lambda er, meta: _score_shipping_efficiency(er),
                strong_text="Shipping operations are efficient and cost-effective",
                weak_text="Shipping efficiency needs improvement",
            ),
            ScoreComponent(
                name="forecast_accuracy",
                scorer=lambda er, meta: _score_forecast_accuracy(er),
                strong_text="Demand forecasts are accurate and actionable",
                weak_text="Forecast data is thin — predictions may be unreliable",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_stock_health(results: dict[str, Any]) -> float:
    """Score inventory health."""
    score = 0

    inv = results.get("inventory", {})
    if isinstance(inv, dict) and inv.get("status") == "success":
        inv_data = inv.get("data") or {}
        if inv_data.get("inventory_health"):
            score += 8
        if inv_data.get("reorder_plan"):
            score += 7
        stockout_risks = inv_data.get("stockout_risks", [])
        if isinstance(stockout_risks, list):
            if len(stockout_risks) == 0:
                score += 10
            elif len(stockout_risks) < 5:
                score += 5
            else:
                score += 2

    return min(25, score)


def _score_supplier_reliability(results: dict[str, Any]) -> float:
    """Score supplier dependability."""
    score = 0

    sup = results.get("supplier", {})
    if isinstance(sup, dict) and sup.get("status") == "success":
        sup_data = sup.get("data") or {}
        if sup_data.get("supplier_scores"):
            score += 12
            supplier_scores = sup_data["supplier_scores"]
            if isinstance(supplier_scores, list) and len(supplier_scores) > 0:
                score += 5

    sd = results.get("supplier_discovery", {})
    if isinstance(sd, dict) and sd.get("status") == "success":
        sd_data = sd.get("data") or {}
        if sd_data.get("new_suppliers"):
            score += 8

    return min(25, score)


def _score_shipping_efficiency(results: dict[str, Any]) -> float:
    """Score shipping and fulfillment."""
    score = 0

    ship = results.get("shipping_optimization", {})
    if isinstance(ship, dict) and ship.get("status") == "success":
        ship_data = ship.get("data") or {}
        if ship_data.get("shipping_plan"):
            score += 15
            plan = ship_data["shipping_plan"]
            if isinstance(plan, dict) and plan.get("optimized_routes"):
                score += 5
            if isinstance(plan, dict) and plan.get("cost_savings"):
                score += 5

    return min(25, score)


def _score_forecast_accuracy(results: dict[str, Any]) -> float:
    """Score stock forecast reliability."""
    score = 0

    sp = results.get("stock_prediction", {})
    if isinstance(sp, dict) and sp.get("status") == "success":
        sp_data = sp.get("data") or {}
        if sp_data.get("stock_forecast"):
            score += 12
            forecast = sp_data["stock_forecast"]
            if isinstance(forecast, dict):
                if forecast.get("confidence"):
                    score += 5
                if forecast.get("horizon_days"):
                    score += 4
                if forecast.get("seasonal_adjustment"):
                    score += 4

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    inv = results.get("inventory", {})
    has_stockout_risks = False
    if isinstance(inv, dict) and inv.get("status") == "success":
        risks = (inv.get("data") or {}).get("stockout_risks", [])
        has_stockout_risks = isinstance(risks, list) and len(risks) > 0

    if score >= 70:
        if has_stockout_risks:
            return "Operations are strong overall but reorders should be placed for at-risk items."
        return "Operations are running smoothly. Continue monitoring and optimizing."

    if score >= 40:
        return "Operations show some gaps. Review supplier reliability and inventory levels."

    return "Operations need attention. Recommend immediate review of stock levels and supplier performance."
