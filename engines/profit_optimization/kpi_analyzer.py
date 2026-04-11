"""Profit Optimization Engine — KPI analyzer.

Analyzes key performance indicators: ROAS, CPA, CLV, AOV,
conversion rate, cart abandonment, margin trends, and health scores.

Model note: Would use Mistral for KPI analysis and decision logic.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Industry benchmarks for health assessment
# ---------------------------------------------------------------------------

_BENCHMARKS = {
    "roas_good": 4.0,
    "roas_acceptable": 2.0,
    "cpa_good_ratio": 0.15,      # CPA < 15% of AOV is good
    "cpa_acceptable_ratio": 0.30, # CPA < 30% of AOV is acceptable
    "conversion_good": 0.03,
    "conversion_excellent": 0.05,
    "abandonment_good": 0.60,
    "abandonment_acceptable": 0.75,
    "margin_good": 0.20,
    "margin_acceptable": 0.10,
}


def analyze_kpis(
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Analyze KPIs from aggregated data and profit metrics.

    Computes real KPI values and assesses health against benchmarks.

    Args:
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.

    Returns:
        Structured dict with KPIResult.
    """
    try:
        data = copy.deepcopy(aggregated)
        metrics = copy.deepcopy(profit_metrics)

        sales = data.get("sales", {})
        ads = data.get("ads", {})
        perf = data.get("performance", {})

        total_revenue = float(sales.get("total_revenue", 0.0))
        orders = int(sales.get("orders", 0))
        units_sold = int(sales.get("units_sold", 0))
        ad_spend = float(ads.get("total_spend", 0.0))
        impressions = int(ads.get("impressions", 0))
        clicks = int(ads.get("clicks", 0))
        conversions = int(ads.get("conversions", 0))

        # --- Core KPIs ---
        roas = total_revenue / ad_spend if ad_spend > 0 else 0.0
        cpa = ad_spend / conversions if conversions > 0 else 0.0
        aov = total_revenue / orders if orders > 0 else 0.0

        # CLV estimate: AOV * estimated repeat purchase rate * margin
        # Conservative: assume 2.5x repeat factor for e-commerce
        net_margin = float(metrics.get("net_margin", 0.0))
        clv_estimate = aov * 2.5 * max(net_margin, 0.01)

        conversion_rate = float(perf.get("conversion_rate", 0.0))
        cart_abandonment = float(perf.get("cart_abandonment", 0.0))
        return_rate = float(perf.get("return_rate", 0.0))

        # --- Ad-specific KPIs ---
        cost_per_click = ad_spend / clicks if clicks > 0 else 0.0
        click_through_rate = clicks / impressions if impressions > 0 else 0.0
        ad_conversion_rate = conversions / clicks if clicks > 0 else 0.0

        # --- Health assessments ---
        margin_health = _assess_margin(net_margin)
        roas_health = _assess_roas(roas)
        cpa_health = _assess_cpa(cpa, aov)
        conversion_health = _assess_conversion(conversion_rate)
        abandonment_health = _assess_abandonment(cart_abandonment)

        # Overall health score: weighted average of individual health scores
        health_scores = {
            "margin": _health_to_score(margin_health),
            "roas": _health_to_score(roas_health),
            "cpa": _health_to_score(cpa_health),
            "conversion": _health_to_score(conversion_health),
            "abandonment": _health_to_score(abandonment_health),
        }

        weights = {
            "margin": 0.30,
            "roas": 0.25,
            "cpa": 0.15,
            "conversion": 0.15,
            "abandonment": 0.15,
        }

        health_score = sum(
            health_scores[k] * weights[k] for k in weights
        )

        overall_health = _score_to_health(health_score)

        kpis: dict[str, Any] = {
            "roas": round(roas, 2),
            "cpa": round(cpa, 2),
            "clv_estimate": round(clv_estimate, 2),
            "aov": round(aov, 2),
            "conversion_rate": round(conversion_rate, 4),
            "cart_abandonment": round(cart_abandonment, 4),
            "return_rate": round(return_rate, 4),
            "cost_per_click": round(cost_per_click, 2),
            "click_through_rate": round(click_through_rate, 4),
            "ad_conversion_rate": round(ad_conversion_rate, 4),
            "margin_health": margin_health,
            "roas_health": roas_health,
            "cpa_health": cpa_health,
            "conversion_health": conversion_health,
            "abandonment_health": abandonment_health,
            "overall_health": overall_health,
            "health_score": round(health_score, 4),
        }

        return {
            "status": "success",
            "kpis": kpis,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kpis": {},
            "error": f"KPI analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Health assessment helpers
# ---------------------------------------------------------------------------

def _assess_margin(net_margin: float) -> str:
    if net_margin >= _BENCHMARKS["margin_good"]:
        return "healthy"
    if net_margin >= _BENCHMARKS["margin_acceptable"]:
        return "acceptable"
    if net_margin > 0:
        return "thin"
    return "negative"


def _assess_roas(roas: float) -> str:
    if roas >= _BENCHMARKS["roas_good"]:
        return "strong"
    if roas >= _BENCHMARKS["roas_acceptable"]:
        return "acceptable"
    if roas > 1.0:
        return "weak"
    return "unprofitable"


def _assess_cpa(cpa: float, aov: float) -> str:
    if aov <= 0:
        return "unknown"
    ratio = cpa / aov
    if ratio <= _BENCHMARKS["cpa_good_ratio"]:
        return "efficient"
    if ratio <= _BENCHMARKS["cpa_acceptable_ratio"]:
        return "acceptable"
    return "expensive"


def _assess_conversion(rate: float) -> str:
    if rate >= _BENCHMARKS["conversion_excellent"]:
        return "excellent"
    if rate >= _BENCHMARKS["conversion_good"]:
        return "good"
    if rate > 0.01:
        return "below_average"
    return "poor"


def _assess_abandonment(rate: float) -> str:
    if rate <= _BENCHMARKS["abandonment_good"]:
        return "good"
    if rate <= _BENCHMARKS["abandonment_acceptable"]:
        return "acceptable"
    return "high"


def _health_to_score(health: str) -> float:
    """Convert a health label to a 0-1 score."""
    mapping = {
        "healthy": 0.9, "strong": 0.9, "efficient": 0.9,
        "excellent": 1.0, "good": 0.8,
        "acceptable": 0.6,
        "thin": 0.3, "weak": 0.3, "below_average": 0.4,
        "expensive": 0.2, "high": 0.3,
        "negative": 0.0, "unprofitable": 0.1, "poor": 0.1,
        "unknown": 0.5,
    }
    return mapping.get(health, 0.5)


def _score_to_health(score: float) -> str:
    """Convert a 0-1 score to an overall health label."""
    if score >= 0.8:
        return "strong"
    if score >= 0.6:
        return "good"
    if score >= 0.4:
        return "needs_attention"
    if score >= 0.2:
        return "concerning"
    return "critical"
