"""Finance Agent evaluator — assess quality of financial analysis results.

Evaluates:
  - Financial clarity (is the P&L and margin picture clear?)
  - Forecast confidence (are forecasts reliable?)
  - Pricing quality (are pricing recommendations data-driven?)
  - Actionability (can we act on the findings immediately?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate financial analysis quality.

    Returns score 0-100 with detailed breakdown.
    """
    engine_results = results.get("engine_results", {})
    completed = results.get("completed_steps", 0)
    total = results.get("total_steps", 1)

    scores: dict[str, float] = {}
    issues: list[str] = []
    strengths: list[str] = []

    # 1. Financial clarity (0-25): Is the financial picture clear?
    financial_clarity = _score_financial_clarity(engine_results)
    scores["financial_clarity"] = financial_clarity
    if financial_clarity >= 20:
        strengths.append("Clear P&L, margins, and financial health assessment")
    elif financial_clarity < 10:
        issues.append("Financial data is incomplete — unclear picture of health")

    # 2. Forecast confidence (0-25): Are forecasts reliable?
    forecast_confidence = _score_forecast_confidence(engine_results)
    scores["forecast_confidence"] = forecast_confidence
    if forecast_confidence >= 20:
        strengths.append("Revenue forecasts backed by strong historical data")
    elif forecast_confidence < 10:
        issues.append("Forecasts are unreliable — insufficient historical data")

    # 3. Pricing quality (0-25): Are pricing recommendations solid?
    pricing_quality = _score_pricing_quality(engine_results)
    scores["pricing_quality"] = pricing_quality
    if pricing_quality >= 20:
        strengths.append("Pricing recommendations supported by elasticity and market data")
    elif pricing_quality < 10:
        issues.append("Pricing analysis is weak — recommendations may not optimize revenue")

    # 4. Actionability (0-25): Can we act on findings?
    actionability = _score_actionability(engine_results, completed, total)
    scores["actionability"] = actionability
    if actionability >= 20:
        strengths.append("Clear actionable steps with measurable impact estimates")
    elif actionability < 10:
        issues.append("No clear actionable recommendations from analysis")

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


def _score_financial_clarity(results: dict[str, Any]) -> float:
    """Score how clear the financial picture is."""
    score = 0

    # Financial engine results
    fin = results.get("financial", {})
    if fin.get("status") == "success":
        fin_data = fin.get("data", {})
        if fin_data.get("pnl"):
            score += 7
        if fin_data.get("margins"):
            score += 6
        if fin_data.get("health_grade"):
            score += 5

    # Profitability calculator results
    pc = results.get("profitability_calculator", {})
    if pc.get("status") == "success":
        pc_data = pc.get("data", {})
        if pc_data.get("true_costs"):
            score += 4
        if pc_data.get("cost_breakdown"):
            score += 3

    return min(25, score)


def _score_forecast_confidence(results: dict[str, Any]) -> float:
    """Score how confident the forecasts are."""
    score = 0

    # Forecasting engine results
    fc = results.get("forecasting", {})
    if fc.get("status") == "success":
        fc_data = fc.get("data", {})
        if fc_data.get("revenue_forecast"):
            score += 8
        if fc_data.get("confidence_interval"):
            score += 5
        if fc_data.get("seasonality_factors"):
            score += 4

    # KPI tracking results
    kpi = results.get("kpi_tracking", {})
    if kpi.get("status") == "success":
        kpi_data = kpi.get("data", {})
        if kpi_data.get("kpi_trends"):
            score += 5
        if kpi_data.get("trend_direction"):
            score += 3

    return min(25, score)


def _score_pricing_quality(results: dict[str, Any]) -> float:
    """Score how well pricing analysis was done."""
    score = 0

    # Pricing engine results
    pr = results.get("pricing", {})
    if pr.get("status") == "success":
        pr_data = pr.get("data", {})
        if pr_data.get("price_recommendations"):
            score += 6
        if pr_data.get("competitor_analysis"):
            score += 4

    # Dynamic pricing results
    dp = results.get("dynamic_pricing", {})
    if dp.get("status") == "success":
        dp_data = dp.get("data", {})
        if dp_data.get("price_adjustments"):
            score += 5

    # Price elasticity results
    pe = results.get("price_elasticity", {})
    if pe.get("status") == "success":
        pe_data = pe.get("data", {})
        if pe_data.get("elasticity_curves"):
            score += 5

    # Discount strategy results
    ds = results.get("discount_strategy", {})
    if ds.get("status") == "success":
        ds_data = ds.get("data", {})
        if ds_data.get("discount_plan"):
            score += 5

    return min(25, score)


def _score_actionability(results: dict[str, Any], completed: int, total: int) -> float:
    """Score how actionable the results are."""
    score = 0

    # Base score from engine completion rate
    score += round(completed / max(total, 1) * 10)

    # Financial engine provides clear health grade?
    fin = results.get("financial", {})
    if fin.get("status") == "success":
        fin_data = fin.get("data", {})
        if fin_data.get("health_grade"):
            score += 5
        if fin_data.get("recommendations"):
            score += 3

    # Profit optimization provides clear plan?
    po = results.get("profit_optimization", {})
    if po.get("status") == "success":
        po_data = po.get("data", {})
        if po_data.get("profit_plan"):
            score += 5
        if po_data.get("estimated_impact"):
            score += 2

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    fin = results.get("financial", {})
    health_grade = ""
    if fin.get("status") == "success":
        health_grade = fin.get("data", {}).get("health_grade", "")

    if score >= 70:
        if health_grade in ("A", "B"):
            return "Financial health is strong. Implement pricing optimizations to grow margins."
        return "Analysis quality is high. Review specific recommendations to improve financial health."

    if score >= 40:
        return "Financial picture is partially clear. Gather more data on costs and pricing to make confident decisions."

    return "Financial analysis is insufficient. Collect order history and cost data before making pricing changes."
