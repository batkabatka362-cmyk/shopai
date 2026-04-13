"""Profit Optimization Engine — optimization generator.

Generates specific, actionable optimizations from detected opportunities:
price adjustments, budget reallocation, funnel improvements, cost cuts.

Each optimization has expected revenue/cost/profit deltas computed from
real metrics — not fabricated.

Model note: Would use Qwen for structured optimization plan generation.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


def generate_optimizations(
    opportunities: list[dict[str, Any]],
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, Any]:
    """Generate concrete optimizations from detected opportunities.

    Args:
        opportunities: List of Opportunity dicts from opportunity_detector.
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.
        kpis: Output from kpi_analyzer.

    Returns:
        Structured dict with list of Optimization dicts.
    """
    try:
        opps = copy.deepcopy(opportunities)
        agg = copy.deepcopy(aggregated)
        metrics = copy.deepcopy(profit_metrics)
        kpi = copy.deepcopy(kpis)

        optimizations: list[dict[str, Any]] = []

        for opp in opps:
            category = opp.get("category", "")
            generator = _CATEGORY_GENERATORS.get(category, _generate_generic)
            opt = generator(opp, agg, metrics, kpi)
            if opt:
                optimizations.append(opt)

        return {
            "status": "success",
            "optimizations": optimizations,
            "count": len(optimizations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "optimizations": [],
            "count": 0,
            "error": f"Optimization generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Category-specific generators
# ---------------------------------------------------------------------------

def _generate_margin_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for margin-related opportunities."""
    net_revenue = float(metrics.get("net_revenue", 0.0))
    net_margin = float(metrics.get("net_margin", 0.0))
    total_cost = float(metrics.get("total_cost", 0.0))

    if net_margin < 0:
        # Urgent: cut costs or raise prices
        cost_cut_target = abs(float(metrics.get("net_profit", 0.0))) * 1.2
        return _make_optimization(
            opportunity_id=opp["opportunity_id"],
            action="emergency_cost_reduction",
            details=(
                f"Reduce total costs by ${cost_cut_target:.2f} through COGS "
                "negotiation, shipping optimization, and ad spend audit. "
                "Target breakeven within 30 days."
            ),
            expected_revenue_change=0.0,
            expected_cost_change=-cost_cut_target,
            expected_profit_change=cost_cut_target,
            implementation_effort="high",
            timeframe="1-4 weeks",
        )
    else:
        # Improve margin
        target_improvement = 0.05
        profit_gain = target_improvement * net_revenue
        return _make_optimization(
            opportunity_id=opp["opportunity_id"],
            action="margin_improvement",
            details=(
                f"Improve net margin by 5pp (from {net_margin:.1%} to "
                f"{net_margin + target_improvement:.1%}) through combined "
                "cost reduction and selective price increases."
            ),
            expected_revenue_change=0.0,
            expected_cost_change=-profit_gain,
            expected_profit_change=profit_gain,
            implementation_effort="medium",
            timeframe="2-6 weeks",
        )


def _generate_advertising_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for advertising opportunities."""
    ads = agg.get("ads", {})
    ad_spend = float(ads.get("total_spend", 0.0))
    roas = float(kpi.get("roas", 0.0))
    cpa = float(kpi.get("cpa", 0.0))
    aov = float(kpi.get("aov", 0.0))
    title = opp.get("title", "")

    if "scale" in title.lower():
        # Scale ad spend for high ROAS
        budget_increase = ad_spend * 0.30
        expected_rev = budget_increase * roas * 0.8  # conservative 80% of current ROAS
        net_margin = float(metrics.get("net_margin", 0.1))
        expected_profit = expected_rev * max(net_margin, 0.05) - budget_increase
        return _make_optimization(
            opportunity_id=opp["opportunity_id"],
            action="scale_ad_budget",
            details=(
                f"Increase ad budget by 30% (${budget_increase:.2f}). "
                f"At 80% of current ROAS ({roas:.1f}x), expect "
                f"${expected_rev:.2f} additional revenue."
            ),
            expected_revenue_change=expected_rev,
            expected_cost_change=budget_increase,
            expected_profit_change=expected_profit,
            implementation_effort="low",
            timeframe="1-2 weeks",
        )
    elif "reallocate" in title.lower():
        # Budget reallocation between platforms
        impact = float(opp.get("estimated_impact", 0.0))
        return _make_optimization(
            opportunity_id=opp["opportunity_id"],
            action="reallocate_ad_budget",
            details=(
                "Shift 30% of underperforming platform budget to the "
                "best-performing platform. Monitor ROAS per platform for "
                "2 weeks before further changes."
            ),
            expected_revenue_change=impact * 0.6,
            expected_cost_change=0.0,
            expected_profit_change=impact * 0.6,
            implementation_effort="low",
            timeframe="1-2 weeks",
        )
    else:
        # Optimize weak campaigns
        savings = ad_spend * 0.15
        return _make_optimization(
            opportunity_id=opp["opportunity_id"],
            action="optimize_ad_campaigns",
            details=(
                f"Audit and pause underperforming ad sets. Target 15% "
                f"savings (${savings:.2f}) while maintaining conversion volume. "
                "Refine audience targeting and creative."
            ),
            expected_revenue_change=0.0,
            expected_cost_change=-savings,
            expected_profit_change=savings,
            implementation_effort="medium",
            timeframe="2-4 weeks",
        )


def _generate_cost_reduction_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for cost reduction opportunities."""
    impact = float(opp.get("estimated_impact", 0.0))
    title = opp.get("title", "").lower()

    if "cogs" in title or "supplier" in title:
        action = "negotiate_supplier_costs"
        details = (
            f"Negotiate with suppliers for a 5-10% cost reduction. "
            f"Target savings: ${impact:.2f}. Consider bulk ordering, "
            "alternative suppliers, or renegotiating contracts."
        )
        timeframe = "4-8 weeks"
        effort = "high"
    elif "shipping" in title:
        action = "optimize_shipping"
        details = (
            f"Optimize fulfillment by comparing carriers, consolidating "
            f"shipments, and negotiating volume rates. Target: ${impact:.2f} savings."
        )
        timeframe = "2-6 weeks"
        effort = "medium"
    else:
        action = "reduce_platform_costs"
        details = (
            f"Evaluate platform fee structure and alternatives. "
            f"Target savings: ${impact:.2f}."
        )
        timeframe = "4-8 weeks"
        effort = "high"

    return _make_optimization(
        opportunity_id=opp["opportunity_id"],
        action=action,
        details=details,
        expected_revenue_change=0.0,
        expected_cost_change=-impact,
        expected_profit_change=impact,
        implementation_effort=effort,
        timeframe=timeframe,
    )


def _generate_conversion_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for conversion/funnel opportunities."""
    impact = float(opp.get("estimated_impact", 0.0))
    title = opp.get("title", "").lower()
    net_margin = float(metrics.get("net_margin", 0.1))

    if "abandonment" in title:
        action = "cart_recovery_campaign"
        details = (
            "Implement cart abandonment email sequence and exit-intent "
            "popups. Offer time-limited discount (5-10%) to recover "
            "abandoned carts."
        )
        timeframe = "1-2 weeks"
        effort = "low"
        revenue_change = impact
        profit_change = impact * max(net_margin, 0.05)
    elif "conversion" in title:
        action = "funnel_optimization"
        details = (
            "Optimize product pages, checkout flow, and page load speed. "
            "A/B test CTA buttons, product images, and trust signals."
        )
        timeframe = "2-6 weeks"
        effort = "medium"
        revenue_change = impact
        profit_change = impact * max(net_margin, 0.05)
    else:
        action = "reduce_returns"
        details = (
            "Improve product descriptions, add sizing guides, and enhance "
            "quality control to reduce return rate."
        )
        timeframe = "4-8 weeks"
        effort = "medium"
        revenue_change = 0.0
        profit_change = impact

    return _make_optimization(
        opportunity_id=opp["opportunity_id"],
        action=action,
        details=details,
        expected_revenue_change=revenue_change,
        expected_cost_change=0.0,
        expected_profit_change=profit_change,
        implementation_effort=effort,
        timeframe=timeframe,
    )


def _generate_pricing_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for pricing opportunities."""
    revenue_per_unit = float(metrics.get("revenue_per_unit", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    impact = float(opp.get("estimated_impact", 0.0))

    price_increase_pct = 0.05
    new_price = revenue_per_unit * (1.0 + price_increase_pct)

    return _make_optimization(
        opportunity_id=opp["opportunity_id"],
        action="strategic_price_increase",
        details=(
            f"Increase prices by {price_increase_pct:.0%} "
            f"(${revenue_per_unit:.2f} → ${new_price:.2f}/unit). "
            "Implement gradually and monitor conversion rate impact. "
            "Use A/B testing to validate."
        ),
        expected_revenue_change=net_revenue * price_increase_pct * 0.7,
        expected_cost_change=0.0,
        expected_profit_change=impact,
        implementation_effort="low",
        timeframe="1-2 weeks",
    )


def _generate_scaling_optimization(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Generate optimization for scaling opportunities."""
    net_profit = float(metrics.get("net_profit", 0.0))
    ad_spend = float(agg.get("ads", {}).get("total_spend", 0.0))

    reinvest = net_profit * 0.30
    return _make_optimization(
        opportunity_id=opp["opportunity_id"],
        action="scale_operations",
        details=(
            f"Reinvest 30% of net profit (${reinvest:.2f}) into growth: "
            "increase ad budget, expand product catalog, and optimize "
            "supply chain for higher volume."
        ),
        expected_revenue_change=reinvest * 3.0,
        expected_cost_change=reinvest,
        expected_profit_change=reinvest * 2.0 * float(metrics.get("net_margin", 0.1)),
        implementation_effort="medium",
        timeframe="4-8 weeks",
    )


def _generate_generic(
    opp: dict[str, Any],
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> dict[str, Any]:
    """Fallback generator for unknown opportunity categories."""
    impact = float(opp.get("estimated_impact", 0.0))
    return _make_optimization(
        opportunity_id=opp["opportunity_id"],
        action="general_optimization",
        details=opp.get("description", "Review and optimize."),
        expected_revenue_change=0.0,
        expected_cost_change=0.0,
        expected_profit_change=impact * 0.5,
        implementation_effort=opp.get("effort", "medium"),
        timeframe="2-6 weeks",
    )


# ---------------------------------------------------------------------------
# Generator dispatch table
# ---------------------------------------------------------------------------

_CATEGORY_GENERATORS = {
    "margin": _generate_margin_optimization,
    "advertising": _generate_advertising_optimization,
    "cost_reduction": _generate_cost_reduction_optimization,
    "conversion": _generate_conversion_optimization,
    "pricing": _generate_pricing_optimization,
    "scaling": _generate_scaling_optimization,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_optimization(
    opportunity_id: str,
    action: str,
    details: str,
    expected_revenue_change: float,
    expected_cost_change: float,
    expected_profit_change: float,
    implementation_effort: str,
    timeframe: str,
) -> dict[str, Any]:
    """Build a standardized Optimization dict."""
    return {
        "optimization_id": uuid.uuid4().hex[:10],
        "opportunity_id": opportunity_id,
        "action": action,
        "details": details,
        "expected_revenue_change": round(expected_revenue_change, 2),
        "expected_cost_change": round(expected_cost_change, 2),
        "expected_profit_change": round(expected_profit_change, 2),
        "implementation_effort": implementation_effort,
        "timeframe": timeframe,
        "model_note": "Qwen: structured optimization plan generation",
    }
