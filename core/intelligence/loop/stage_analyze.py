"""Stage 2: ANALYZE — compute scores, detect patterns, assess opportunity."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("intelligence.loop.analyze")
from core.intelligence.loop.helpers import _calc_opportunity


def stage_analyze(data: dict[str, Any], goal: str) -> dict[str, Any]:
    analysis = {"goal": goal, "findings": []}

    # Product analysis
    products = data.get("products", data.get("product_data", []))
    if isinstance(products, list) and products:
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products(products)
        viable = [p for p in scored if p.get("viable")]
        top = sorted(scored, key=lambda p: p.get("total_score", 0), reverse=True)

        analysis["products"] = {
            "total": len(products),
            "viable": len(viable),
            "top_product": top[0] if top else {},
            "avg_score": round(sum(p.get("total_score", 0) for p in scored) / max(len(scored), 1), 2),
            "scored": scored,
        }

        if viable:
            analysis["findings"].append(f"{len(viable)}/{len(products)} products viable")
        if top and top[0].get("total_score", 0) > 8:
            analysis["findings"].append(f"Strong candidate: {top[0].get('name')} (score {top[0]['total_score']})")

    # Customer analysis
    customers = data.get("customer_data", data.get("customers", []))
    if isinstance(customers, list) and customers:
        repeat = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("orders")) > 1)
        at_risk = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("days_since_last_order")) > 60)
        analysis["customers"] = {
            "total": len(customers),
            "repeat_rate": round(repeat / max(len(customers), 1) * 100, 1),
            "at_risk": at_risk,
        }
        if at_risk > 0:
            analysis["findings"].append(f"{at_risk} customers at churn risk")

    # Revenue analysis
    orders = data.get("orders", data.get("order_data", []))
    if isinstance(orders, list) and orders:
        revenue = sum(safe_float(o.get("total", o.get("amount", o.get("total_price", 0)))) for o in orders if isinstance(o, dict))
        aov = revenue / max(len(orders), 1)
        analysis["revenue"] = {"total": round(revenue, 2), "orders": len(orders), "aov": round(aov, 2)}
        if aov < 30:
            analysis["findings"].append(f"Low AOV ${aov:.2f} — upsell/bundle opportunity")

    # Revenue forecast — predict future trends
    revenue_series = data.get("daily_revenue", data.get("revenue_history", []))
    if not revenue_series and isinstance(orders, list) and len(orders) >= 3:
        # Build revenue series from orders
        revenue_series = [safe_float(o.get("total", o.get("amount", 0))) for o in orders if isinstance(o, dict)]

    if isinstance(revenue_series, list) and len(revenue_series) >= 3:
        try:
            from core.intelligence.forecasting import Forecasting
            fc = Forecasting()
            forecast = fc.forecast([safe_float(v) for v in revenue_series if safe_float(v) > 0], periods=7)
            if "error" not in forecast:
                growth = safe_float(forecast.get("summary", {}).get("growth_pct"))
                trend = forecast.get("trend", {})
                analysis["forecast"] = {
                    "method": forecast.get("method"),
                    "growth_pct": growth,
                    "trend_direction": trend.get("direction", "stable"),
                    "forecast_avg": forecast.get("summary", {}).get("forecast_avg", 0),
                    "confidence": forecast.get("confidence_level"),
                }
                if growth > 10:
                    analysis["findings"].append(f"Revenue forecast: +{growth:.1f}% growth — momentum is strong")
                elif growth < -10:
                    analysis["findings"].append(f"Revenue forecast: {growth:.1f}% decline — action needed")
                else:
                    analysis["findings"].append(f"Revenue forecast: {growth:+.1f}% — stable")
        except Exception as exc:
            logger.debug("revenue forecast analysis failed: %s", exc)

    # ── Consume enriched context from CoreOrchestrator ──
    financial_ctx = data.get("_financial", {})
    if financial_ctx.get("net_margin", 100) < 10:
        analysis["findings"].append("WARNING: Net margin below 10% — pricing decisions critical")
        analysis["financial_pressure"] = True
    if financial_ctx.get("margin_alerts_count", 0) > 0:
        analysis["findings"].append(f"Financial: {financial_ctx['margin_alerts_count']} margin alerts active")

    competitive_ctx = data.get("_competitive", {})
    if isinstance(competitive_ctx, dict) and competitive_ctx.get("alerts"):
        alerts = competitive_ctx["alerts"]
        if isinstance(alerts, list) and alerts:
            analysis["findings"].append(f"Competitor activity: {len(alerts)} alerts detected")
            analysis["competitor_active"] = True

    expert_ctx = data.get("_expert", {})
    if isinstance(expert_ctx, dict):
        if expert_ctx.get("reorder_urgent", 0) > 0:
            analysis["findings"].append(f"URGENT: {expert_ctx['reorder_urgent']} products need immediate reorder")
        if expert_ctx.get("creative_fatigue_count", 0) > 0:
            analysis["findings"].append(f"Marketing: {expert_ctx['creative_fatigue_count']} campaigns showing creative fatigue")
        if expert_ctx.get("compliance_violations", 0) > 0:
            analysis["findings"].append(f"Legal: {expert_ctx['compliance_violations']} compliance violations detected")
        if expert_ctx.get("dead_stock_value", 0) > 100:
            analysis["findings"].append(f"Inventory: ${expert_ctx['dead_stock_value']:,.0f} tied up in dead stock")
        lifecycle_action = expert_ctx.get("lifecycle_action")
        if lifecycle_action:
            analysis["findings"].append(f"Customer: {lifecycle_action}")

    # ── Past episodes (similar decisions) ──
    episodes = data.get("_episodes", [])
    if episodes:
        failures = [ep for ep in episodes if not ep.get("success", True)]
        if failures:
            for ep in failures[:2]:
                lesson = ep.get("lesson", "")
                if lesson:
                    analysis["findings"].append(f"HISTORY: {lesson}")
            analysis["past_failure_risk"] = True

    analysis["opportunity_score"] = _calc_opportunity(analysis)
    return analysis
