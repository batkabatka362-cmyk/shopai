"""Profit Optimization Engine — scaler.

Evaluates scaling potential: what to scale up, what to cut, and
detects diminishing returns. Provides guidance on how aggressively
the business can grow without breaking profitability.

No randomness — all scaling analysis is derived from actual metrics.
"""
from __future__ import annotations

import copy
from typing import Any


def evaluate_scaling(
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
    kpis: dict[str, Any],
    optimizations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate scaling potential for the business.

    Analyzes current metrics to determine what can be scaled up,
    what should be cut, and where diminishing returns are likely.

    Args:
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.
        kpis: Output from kpi_analyzer.
        optimizations: List of Optimization dicts.

    Returns:
        Structured dict with scaling analysis.
    """
    try:
        agg = copy.deepcopy(aggregated)
        metrics = copy.deepcopy(profit_metrics)
        kpi = copy.deepcopy(kpis)
        opts = copy.deepcopy(optimizations)

        scale_up = _find_scale_up_candidates(agg, metrics, kpi)
        cut_candidates = _find_cut_candidates(agg, metrics, kpi)
        diminishing = _detect_diminishing_returns(agg, metrics, kpi)
        capacity = _estimate_scaling_capacity(metrics, kpi)

        scaling: dict[str, Any] = {
            "scale_up": scale_up,
            "cut": cut_candidates,
            "diminishing_returns": diminishing,
            "scaling_capacity": capacity,
            "overall_scalability": _compute_overall_scalability(
                scale_up, cut_candidates, diminishing, capacity,
            ),
        }

        return {
            "status": "success",
            "scaling": scaling,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scaling": {},
            "error": f"Scaling evaluation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Scale-up analysis
# ---------------------------------------------------------------------------

def _find_scale_up_candidates(
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Identify areas that can be profitably scaled up."""
    candidates: list[dict[str, Any]] = []
    roas = float(kpi.get("roas", 0.0))
    net_margin = float(metrics.get("net_margin", 0.0))
    ad_spend = float(agg.get("ads", {}).get("total_spend", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    conversion_rate = float(kpi.get("conversion_rate", 0.0))

    # Ad spend scaling
    if roas > 3.0 and net_margin > 0.10:
        max_increase_pct = min((roas - 2.0) * 0.15, 0.50)  # cap at 50%
        max_increase = ad_spend * max_increase_pct
        expected_revenue = max_increase * roas * 0.75  # 75% efficiency at scale
        candidates.append({
            "area": "ad_spend",
            "current_value": round(ad_spend, 2),
            "recommended_increase": round(max_increase, 2),
            "recommended_increase_pct": round(max_increase_pct * 100, 1),
            "expected_additional_revenue": round(expected_revenue, 2),
            "confidence": round(min(0.5 + roas * 0.05, 0.85), 2),
            "rationale": (
                f"ROAS of {roas:.1f}x with {net_margin:.1%} margin supports "
                f"up to {max_increase_pct:.0%} budget increase."
            ),
        })

    # Volume scaling (if unit economics are healthy)
    profit_per_unit = float(metrics.get("profit_per_unit", 0.0))
    revenue_per_unit = float(metrics.get("revenue_per_unit", 0.0))
    units_sold = int(agg.get("summary", {}).get("total_units", 0))

    if profit_per_unit > 0 and revenue_per_unit > 0:
        unit_margin = profit_per_unit / revenue_per_unit
        if unit_margin > 0.08:
            scale_units = int(units_sold * 0.25)
            expected_profit = scale_units * profit_per_unit * 0.85
            candidates.append({
                "area": "order_volume",
                "current_value": units_sold,
                "recommended_increase": scale_units,
                "recommended_increase_pct": 25.0,
                "expected_additional_profit": round(expected_profit, 2),
                "confidence": round(min(unit_margin * 3, 0.80), 2),
                "rationale": (
                    f"Unit margin of {unit_margin:.1%} supports 25% volume "
                    f"increase. Expected ${expected_profit:.2f} additional profit."
                ),
            })

    # Conversion optimization scaling
    if conversion_rate > 0 and conversion_rate < 0.06:
        target_rate = min(conversion_rate * 1.20, 0.08)
        improvement = target_rate - conversion_rate
        additional_orders = 0
        if conversion_rate > 0:
            orders = int(agg.get("summary", {}).get("total_orders", 0))
            traffic = orders / conversion_rate if conversion_rate > 0 else 0
            additional_orders = int(traffic * improvement)
        aov = float(kpi.get("aov", 0.0))
        expected_revenue = additional_orders * aov
        candidates.append({
            "area": "conversion_rate",
            "current_value": round(conversion_rate, 4),
            "recommended_target": round(target_rate, 4),
            "expected_additional_orders": additional_orders,
            "expected_additional_revenue": round(expected_revenue, 2),
            "confidence": 0.55,
            "rationale": (
                f"Improving conversion from {conversion_rate:.2%} to "
                f"{target_rate:.2%} could add {additional_orders} orders."
            ),
        })

    return candidates


# ---------------------------------------------------------------------------
# Cut analysis
# ---------------------------------------------------------------------------

def _find_cut_candidates(
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Identify areas that should be cut or reduced."""
    candidates: list[dict[str, Any]] = []
    net_revenue = float(metrics.get("net_revenue", 0.0))
    costs = agg.get("costs", {})
    ads = agg.get("ads", {})
    roas = float(kpi.get("roas", 0.0))

    if net_revenue <= 0:
        return candidates

    # Unprofitable ad spend
    ad_spend = float(ads.get("total_spend", 0.0))
    if roas > 0 and roas < 1.5 and ad_spend > 0:
        cut_amount = ad_spend * 0.30
        candidates.append({
            "area": "ad_spend",
            "current_value": round(ad_spend, 2),
            "recommended_cut": round(cut_amount, 2),
            "recommended_cut_pct": 30.0,
            "expected_savings": round(cut_amount, 2),
            "rationale": (
                f"ROAS of {roas:.1f}x is below breakeven threshold. "
                f"Cut 30% (${cut_amount:.2f}) from lowest-performing campaigns."
            ),
        })

    # Excessive shipping costs
    shipping = float(costs.get("shipping", 0.0))
    shipping_ratio = shipping / net_revenue
    if shipping_ratio > 0.12:
        target_ratio = 0.10
        savings = (shipping_ratio - target_ratio) * net_revenue
        candidates.append({
            "area": "shipping",
            "current_value": round(shipping, 2),
            "recommended_cut": round(savings, 2),
            "recommended_cut_pct": round((shipping_ratio - target_ratio) / shipping_ratio * 100, 1),
            "expected_savings": round(savings, 2),
            "rationale": (
                f"Shipping at {shipping_ratio:.1%} of revenue exceeds 10% target. "
                f"Reducing could save ${savings:.2f}."
            ),
        })

    # Excessive tool costs relative to revenue
    tools = float(costs.get("tools", 0.0))
    tool_ratio = tools / net_revenue
    if tool_ratio > 0.03:
        savings = (tool_ratio - 0.02) * net_revenue
        candidates.append({
            "area": "tools",
            "current_value": round(tools, 2),
            "recommended_cut": round(savings, 2),
            "recommended_cut_pct": round(savings / tools * 100, 1) if tools > 0 else 0,
            "expected_savings": round(savings, 2),
            "rationale": (
                f"Tool costs at {tool_ratio:.1%} of revenue. "
                f"Audit subscriptions for ${savings:.2f} potential savings."
            ),
        })

    return candidates


# ---------------------------------------------------------------------------
# Diminishing returns detection
# ---------------------------------------------------------------------------

def _detect_diminishing_returns(
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect areas showing signs of diminishing returns."""
    warnings: list[dict[str, Any]] = []
    roas = float(kpi.get("roas", 0.0))
    ad_spend = float(agg.get("ads", {}).get("total_spend", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    conversion_rate = float(kpi.get("conversion_rate", 0.0))
    cart_abandonment = float(kpi.get("cart_abandonment", 0.0))

    # Ad spend as % of revenue — high ratio suggests diminishing returns
    if net_revenue > 0:
        ad_ratio = ad_spend / net_revenue
        if ad_ratio > 0.25:
            warnings.append({
                "area": "ad_spend",
                "indicator": f"Ad spend is {ad_ratio:.0%} of revenue",
                "risk": "Further ad spend increases may yield lower marginal ROAS",
                "threshold": "Ad spend above 25% of revenue typically shows diminishing returns",
                "severity": "medium" if ad_ratio < 0.35 else "high",
            })

    # High conversion rate may be near ceiling
    if conversion_rate > 0.07:
        warnings.append({
            "area": "conversion_rate",
            "indicator": f"Conversion rate is already {conversion_rate:.1%}",
            "risk": "Further funnel optimization will yield smaller gains",
            "threshold": "Rates above 7% are in the top tier for e-commerce",
            "severity": "low",
        })

    # Low cart abandonment — less room to improve
    if cart_abandonment < 0.50 and cart_abandonment > 0:
        warnings.append({
            "area": "cart_abandonment",
            "indicator": f"Cart abandonment at {cart_abandonment:.0%} is already low",
            "risk": "Cart recovery campaigns will have lower yield",
            "threshold": "Below 50% is excellent for e-commerce",
            "severity": "low",
        })

    return warnings


# ---------------------------------------------------------------------------
# Scaling capacity estimation
# ---------------------------------------------------------------------------

def _estimate_scaling_capacity(
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Estimate how much the business can scale before hitting limits."""
    net_margin = float(metrics.get("net_margin", 0.0))
    net_profit = float(metrics.get("net_profit", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    roas = float(kpi.get("roas", 0.0))
    health_score = float(kpi.get("health_score", 0.0))

    # Max additional ad spend before margins go to zero
    if net_margin > 0 and net_revenue > 0:
        # How much additional cost can we absorb?
        max_additional_cost = net_profit * 0.70  # keep 30% profit buffer
        max_ad_budget_increase = max_additional_cost
    else:
        max_ad_budget_increase = 0.0

    # Revenue headroom before needing operational changes
    if net_margin > 0.05:
        # Can roughly double at current margins with proportional cost growth
        revenue_headroom = net_revenue * (net_margin / 0.05 - 1.0)
        revenue_headroom = min(revenue_headroom, net_revenue * 3.0)  # cap at 3x
    else:
        revenue_headroom = 0.0

    # Overall scaling score 0-1
    factors = []
    if net_margin > 0:
        factors.append(min(net_margin / 0.20, 1.0))
    else:
        factors.append(0.0)
    if roas > 0:
        factors.append(min(roas / 5.0, 1.0))
    else:
        factors.append(0.0)
    factors.append(health_score)

    scaling_score = sum(factors) / len(factors) if factors else 0.0

    if scaling_score >= 0.7:
        readiness = "ready_to_scale"
    elif scaling_score >= 0.4:
        readiness = "optimize_first"
    else:
        readiness = "not_ready"

    return {
        "scaling_score": round(scaling_score, 2),
        "readiness": readiness,
        "max_ad_budget_increase": round(max_ad_budget_increase, 2),
        "revenue_headroom": round(revenue_headroom, 2),
        "constraints": _identify_constraints(metrics, kpi),
    }


def _identify_constraints(
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[str]:
    """Identify constraints that limit scaling."""
    constraints: list[str] = []
    net_margin = float(metrics.get("net_margin", 0.0))
    roas = float(kpi.get("roas", 0.0))
    conversion_rate = float(kpi.get("conversion_rate", 0.0))
    health_score = float(kpi.get("health_score", 0.0))

    if net_margin < 0.05:
        constraints.append("Thin margins limit reinvestment capacity")
    if roas < 2.0:
        constraints.append("Low ROAS means ad spend scaling is risky")
    if conversion_rate < 0.02:
        constraints.append("Low conversion rate limits traffic monetization")
    if health_score < 0.5:
        constraints.append("Overall health score too low for aggressive scaling")
    if not constraints:
        constraints.append("No major constraints identified")

    return constraints


# ---------------------------------------------------------------------------
# Overall scalability
# ---------------------------------------------------------------------------

def _compute_overall_scalability(
    scale_up: list[dict[str, Any]],
    cuts: list[dict[str, Any]],
    diminishing: list[dict[str, Any]],
    capacity: dict[str, Any],
) -> dict[str, Any]:
    """Compute a summary of overall scalability."""
    scaling_score = float(capacity.get("scaling_score", 0.0))
    num_scale_opportunities = len(scale_up)
    num_cuts_needed = len(cuts)
    num_diminishing_warnings = len(diminishing)

    # Penalty for needed cuts and diminishing returns
    adjusted_score = scaling_score
    adjusted_score -= num_cuts_needed * 0.05
    adjusted_score -= num_diminishing_warnings * 0.03
    adjusted_score += num_scale_opportunities * 0.03
    adjusted_score = max(min(adjusted_score, 1.0), 0.0)

    if adjusted_score >= 0.7:
        verdict = "high"
    elif adjusted_score >= 0.4:
        verdict = "moderate"
    else:
        verdict = "low"

    return {
        "score": round(adjusted_score, 2),
        "verdict": verdict,
        "scale_up_opportunities": num_scale_opportunities,
        "cuts_needed": num_cuts_needed,
        "diminishing_return_warnings": num_diminishing_warnings,
    }
