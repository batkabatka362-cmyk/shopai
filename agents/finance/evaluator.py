"""Finance Agent evaluator — assess quality of financial analysis results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import ScoreComponent, evaluate_results_base


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate financial analysis quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            ScoreComponent(
                name="financial_clarity",
                scorer=lambda er, meta: _score_financial_clarity(er),
                strong_text="Financial picture is clear with P&L, margins, and health grade",
                weak_text="Financial data is incomplete — missing P&L or margin data",
            ),
            ScoreComponent(
                name="forecast_confidence",
                scorer=lambda er, meta: _score_forecast_confidence(er),
                strong_text="Forecasts are well-supported by historical data",
                weak_text="Forecasting data is insufficient for reliable projections",
            ),
            ScoreComponent(
                name="pricing_quality",
                scorer=lambda er, meta: _score_pricing_quality(er),
                strong_text="Pricing analysis is thorough with clear recommendations",
                weak_text="Pricing analysis is weak — lacks data or recommendations",
            ),
            ScoreComponent(
                name="actionability",
                scorer=lambda er, meta: _score_actionability(er, meta["completed"], meta["total"]),
                strong_text="Clear actionable recommendations with expected impact",
                weak_text="No clear actionable recommendations",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_financial_clarity(results: dict[str, Any]) -> float:
    """Score how clear the financial picture is."""
    score = 0

    fin = results.get("financial", {})
    if isinstance(fin, dict) and fin.get("status") == "success":
        fin_data = fin.get("data") or {}
        if fin_data.get("pnl"):
            score += 7
        if fin_data.get("margins"):
            score += 6
        if fin_data.get("health_grade"):
            score += 5

    pc = results.get("profitability_calculator", {})
    if isinstance(pc, dict) and pc.get("status") == "success":
        pc_data = pc.get("data") or {}
        if pc_data.get("true_costs"):
            score += 4
        if pc_data.get("cost_breakdown"):
            score += 3

    return min(25, score)


def _score_forecast_confidence(results: dict[str, Any]) -> float:
    """Score how confident the forecasts are."""
    score = 0

    fc = results.get("forecasting", {})
    if isinstance(fc, dict) and fc.get("status") == "success":
        fc_data = fc.get("data") or {}
        if fc_data.get("revenue_forecast"):
            score += 8
        if fc_data.get("confidence_interval"):
            score += 5
        if fc_data.get("seasonality_factors"):
            score += 4

    kpi = results.get("kpi_tracking", {})
    if isinstance(kpi, dict) and kpi.get("status") == "success":
        kpi_data = kpi.get("data") or {}
        if kpi_data.get("kpi_trends"):
            score += 5
        if kpi_data.get("trend_direction"):
            score += 3

    return min(25, score)


def _score_pricing_quality(results: dict[str, Any]) -> float:
    """Score how well pricing analysis was done."""
    score = 0

    pr = results.get("pricing", {})
    if isinstance(pr, dict) and pr.get("status") == "success":
        pr_data = pr.get("data") or {}
        if pr_data.get("price_recommendations"):
            score += 6
        if pr_data.get("competitor_analysis"):
            score += 4

    dp = results.get("dynamic_pricing", {})
    if isinstance(dp, dict) and dp.get("status") == "success":
        dp_data = dp.get("data") or {}
        if dp_data.get("price_adjustments"):
            score += 5

    pe = results.get("price_elasticity", {})
    if isinstance(pe, dict) and pe.get("status") == "success":
        pe_data = pe.get("data") or {}
        if pe_data.get("elasticity_curves"):
            score += 5

    ds = results.get("discount_strategy", {})
    if isinstance(ds, dict) and ds.get("status") == "success":
        ds_data = ds.get("data") or {}
        if ds_data.get("discount_plan"):
            score += 5

    return min(25, score)


def _score_actionability(results: dict[str, Any], completed: int, total: int) -> float:
    """Score how actionable the results are."""
    score = 0

    # Base score from engine completion rate
    score += round(completed / max(total, 1) * 10)

    fin = results.get("financial", {})
    if isinstance(fin, dict) and fin.get("status") == "success":
        fin_data = fin.get("data") or {}
        if fin_data.get("health_grade"):
            score += 5
        if fin_data.get("recommendations"):
            score += 3

    po = results.get("profit_optimization", {})
    if isinstance(po, dict) and po.get("status") == "success":
        po_data = po.get("data") or {}
        if po_data.get("profit_plan"):
            score += 5
        if po_data.get("estimated_impact"):
            score += 2

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    fin = results.get("financial", {})
    health_grade = ""
    if isinstance(fin, dict) and fin.get("status") == "success":
        health_grade = (fin.get("data") or {}).get("health_grade", "")

    if score >= 70:
        if health_grade in ("A", "B"):
            return "Financial health is strong. Implement pricing optimizations to grow margins."
        return "Analysis quality is high. Review specific recommendations to improve financial health."

    if score >= 40:
        return "Financial picture is partially clear. Gather more data on costs and pricing to make confident decisions."

    return "Financial analysis is insufficient. Collect order history and cost data before making pricing changes."
