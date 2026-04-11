"""Learning Loop — result collector.

Collects and normalizes execution results, extracts key metrics,
and computes derived metrics (CTR, conversion rate, CPA, ROAS, etc.).

No model needed — pure computation.
"""
from __future__ import annotations

import copy
from typing import Any


def collect_results(
    task: str,
    decision: str,
    execution: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Collect, normalize, and enrich execution results with derived metrics.

    Args:
        task: The task that was executed.
        decision: The decision that led to execution.
        execution: Description of what was executed.
        result: Raw result metrics.

    Returns:
        Structured dict with raw metrics, derived metrics, and summary.
    """
    try:
        raw = copy.deepcopy(result) if result else {}

        views = _safe_num(raw.get("views", raw.get("impressions", 0)))
        clicks = _safe_num(raw.get("clicks", 0))
        sales = _safe_num(raw.get("sales", raw.get("orders", 0)))
        revenue = _safe_num(raw.get("revenue", 0.0))
        cost = _safe_num(raw.get("cost", 0.0))
        sessions = _safe_num(raw.get("sessions", views))
        returns = _safe_num(raw.get("returns", 0))
        engagements = _safe_num(raw.get("engagements", clicks))
        bounce_rate = _safe_num(raw.get("bounce_rate", 0.0))

        ctr = (clicks / views * 100.0) if views > 0 else 0.0
        conversion_rate = (sales / clicks * 100.0) if clicks > 0 else 0.0
        view_to_sale_rate = (sales / views * 100.0) if views > 0 else 0.0
        cpa = (cost / sales) if sales > 0 else 0.0
        roas = (revenue / cost) if cost > 0 else 0.0
        profit = revenue - cost
        profit_margin = (profit / revenue * 100.0) if revenue > 0 else 0.0
        avg_order_value = (revenue / sales) if sales > 0 else 0.0
        return_rate = (returns / sales * 100.0) if sales > 0 else 0.0
        engagement_rate = (engagements / views * 100.0) if views > 0 else 0.0

        raw_metrics = {
            "views": views,
            "clicks": clicks,
            "sales": sales,
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "sessions": sessions,
            "returns": returns,
            "engagements": engagements,
            "bounce_rate": round(bounce_rate, 2),
        }

        derived_metrics = {
            "ctr": round(ctr, 4),
            "conversion_rate": round(conversion_rate, 4),
            "view_to_sale_rate": round(view_to_sale_rate, 4),
            "cpa": round(cpa, 2),
            "roas": round(roas, 4),
            "profit": round(profit, 2),
            "profit_margin": round(profit_margin, 4),
            "avg_order_value": round(avg_order_value, 2),
            "return_rate": round(return_rate, 4),
            "engagement_rate": round(engagement_rate, 4),
        }

        volume_score = min(views / 10000.0, 1.0) if views > 0 else 0.0
        efficiency_score = min(ctr / 10.0, 1.0) * 0.4 + min(conversion_rate / 10.0, 1.0) * 0.6
        profitability_score = min(max(roas, 0.0) / 5.0, 1.0) if cost > 0 else (0.5 if revenue > 0 else 0.0)
        overall_score = round(
            volume_score * 0.2 + efficiency_score * 0.4 + profitability_score * 0.4,
            4,
        )

        summary = {
            "volume_score": round(volume_score, 4),
            "efficiency_score": round(efficiency_score, 4),
            "profitability_score": round(profitability_score, 4),
            "overall_score": overall_score,
            "has_revenue_data": revenue > 0,
            "has_cost_data": cost > 0,
            "total_metrics_collected": sum(1 for v in raw_metrics.values() if v > 0),
        }

        return {
            "status": "success",
            "task": task,
            "decision": decision,
            "execution": execution,
            "raw_metrics": raw_metrics,
            "derived_metrics": derived_metrics,
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "error",
            "task": task,
            "decision": decision,
            "execution": execution,
            "raw_metrics": {},
            "derived_metrics": {},
            "summary": {},
            "error": str(exc),
        }


def _safe_num(value: Any) -> float:
    """Safely convert a value to a number."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
