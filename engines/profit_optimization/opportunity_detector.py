"""Profit Optimization Engine — opportunity detector.

Detects profit optimization opportunities based on actual metrics:
underpriced products, high-margin items to scale, ad campaigns to
optimize, cost reduction areas.

No guessing — every opportunity is derived from real metric thresholds.

Model note: Would use Mistral for pattern recognition in metrics.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds that trigger opportunity detection
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "high_margin_threshold": 0.50,       # gross margin above 50% = scale candidate
    "low_margin_threshold": 0.10,        # net margin below 10% = pricing issue
    "negative_margin_threshold": 0.0,    # net margin below 0% = urgent
    "roas_weak": 2.0,                    # ROAS below 2 = ad optimization needed
    "roas_strong": 5.0,                  # ROAS above 5 = scale ad spend
    "cpa_expensive_ratio": 0.30,         # CPA > 30% of AOV = too expensive
    "high_abandonment": 0.65,            # cart abandonment above 65%
    "low_conversion": 0.03,              # conversion rate below 3%
    "high_return_rate": 0.05,            # return rate above 5%
    "high_cogs_ratio": 0.60,             # COGS > 60% of revenue
    "high_shipping_ratio": 0.15,         # shipping > 15% of revenue
    "high_platform_fee_ratio": 0.10,     # platform fees > 10% of revenue
    "high_ad_spend_ratio": 0.25,         # ad spend > 25% of revenue
}


def detect_opportunities(
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, Any]:
    """Detect profit optimization opportunities from real metrics.

    Args:
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.
        kpis: Output from kpi_analyzer.

    Returns:
        Structured dict with list of Opportunity dicts.
    """
    try:
        agg = copy.deepcopy(aggregated)
        metrics = copy.deepcopy(profit_metrics)
        kpi = copy.deepcopy(kpis)

        opportunities: list[dict[str, Any]] = []

        # Run each detector; append any opportunities found
        opportunities.extend(_detect_margin_opportunities(metrics))
        opportunities.extend(_detect_ad_opportunities(agg, metrics, kpi))
        opportunities.extend(_detect_cost_reduction_opportunities(agg, metrics))
        opportunities.extend(_detect_conversion_opportunities(agg, kpi))
        opportunities.extend(_detect_pricing_opportunities(metrics, kpi))
        opportunities.extend(_detect_scaling_opportunities(metrics, kpi))

        # Sort by estimated impact descending
        opportunities.sort(
            key=lambda o: float(o.get("estimated_impact", 0.0)),
            reverse=True,
        )

        # Assign priority ranks
        for i, opp in enumerate(opportunities):
            if i < 2:
                opp["priority"] = "critical"
            elif i < 5:
                opp["priority"] = "high"
            elif i < 8:
                opp["priority"] = "medium"
            else:
                opp["priority"] = "low"

        return {
            "status": "success",
            "opportunities": opportunities,
            "count": len(opportunities),
        }
    except Exception as exc:
        return {
            "status": "error",
            "opportunities": [],
            "count": 0,
            "error": f"Opportunity detection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Detector functions — each returns a list of opportunities
# ---------------------------------------------------------------------------

def _detect_margin_opportunities(
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect margin-related opportunities."""
    opps: list[dict[str, Any]] = []
    net_margin = float(metrics.get("net_margin", 0.0))
    gross_margin = float(metrics.get("gross_margin", 0.0))
    net_profit = float(metrics.get("net_profit", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))

    if net_margin < _THRESHOLDS["negative_margin_threshold"]:
        # Losing money — urgent
        opps.append(_make_opportunity(
            category="margin",
            title="Negative net margin — losing money",
            description=(
                f"Net margin is {net_margin:.1%}, resulting in a loss of "
                f"${abs(net_profit):.2f}. Immediate cost reduction or price "
                "increase is required to reach profitability."
            ),
            estimated_impact=abs(net_profit) * 1.5,
            confidence=0.90,
            effort="high",
        ))
    elif net_margin < _THRESHOLDS["low_margin_threshold"]:
        # Thin margins
        target_margin = 0.15
        potential_gain = (target_margin - net_margin) * net_revenue
        opps.append(_make_opportunity(
            category="margin",
            title="Thin net margin — room for improvement",
            description=(
                f"Net margin is {net_margin:.1%}. Improving to 15% would add "
                f"${potential_gain:.2f} in profit."
            ),
            estimated_impact=potential_gain,
            confidence=0.75,
            effort="medium",
        ))

    if gross_margin >= _THRESHOLDS["high_margin_threshold"]:
        # High gross margin but potentially high operating costs
        margin_gap = gross_margin - net_margin
        if margin_gap > 0.25:
            opps.append(_make_opportunity(
                category="margin",
                title="Large gap between gross and net margin",
                description=(
                    f"Gross margin is {gross_margin:.1%} but net margin is only "
                    f"{net_margin:.1%}. Operating costs are eating "
                    f"{margin_gap:.1%} of revenue."
                ),
                estimated_impact=margin_gap * net_revenue * 0.3,
                confidence=0.70,
                effort="medium",
            ))

    return opps


def _detect_ad_opportunities(
    agg: dict[str, Any],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect advertising optimization opportunities."""
    opps: list[dict[str, Any]] = []
    ads = agg.get("ads", {})
    ad_spend = float(ads.get("total_spend", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    roas = float(kpi.get("roas", 0.0))
    cpa = float(kpi.get("cpa", 0.0))
    aov = float(kpi.get("aov", 0.0))

    if ad_spend <= 0:
        return opps

    ad_ratio = ad_spend / net_revenue if net_revenue > 0 else 1.0

    # High ROAS — scale opportunity
    if roas >= _THRESHOLDS["roas_strong"]:
        potential_gain = ad_spend * 0.5 * (roas - 1.0)
        opps.append(_make_opportunity(
            category="advertising",
            title="Strong ROAS — scale ad spend",
            description=(
                f"ROAS is {roas:.1f}x. Increasing ad budget by 50% could "
                f"generate an additional ${potential_gain:.2f} in revenue "
                "assuming similar returns."
            ),
            estimated_impact=potential_gain * 0.3,
            confidence=0.65,
            effort="low",
        ))

    # Weak ROAS — optimize
    if roas < _THRESHOLDS["roas_weak"] and roas > 0:
        wasted = ad_spend * (1.0 - roas / _THRESHOLDS["roas_weak"])
        opps.append(_make_opportunity(
            category="advertising",
            title="Weak ROAS — optimize ad campaigns",
            description=(
                f"ROAS is {roas:.1f}x, below the 2.0x threshold. "
                f"Estimated ${wasted:.2f} in potentially inefficient ad spend."
            ),
            estimated_impact=wasted,
            confidence=0.70,
            effort="medium",
        ))

    # CPA too high relative to AOV
    if aov > 0 and cpa / aov > _THRESHOLDS["cpa_expensive_ratio"]:
        target_cpa = aov * 0.15
        savings = (cpa - target_cpa) * float(ads.get("conversions", 0))
        opps.append(_make_opportunity(
            category="advertising",
            title="CPA too high relative to order value",
            description=(
                f"CPA is ${cpa:.2f} ({cpa/aov:.0%} of AOV ${aov:.2f}). "
                f"Reducing CPA to 15% of AOV could save ${savings:.2f}."
            ),
            estimated_impact=savings,
            confidence=0.60,
            effort="medium",
        ))

    # Ad spend ratio too high
    if ad_ratio > _THRESHOLDS["high_ad_spend_ratio"]:
        excess = (ad_ratio - 0.20) * net_revenue
        opps.append(_make_opportunity(
            category="advertising",
            title="Ad spend ratio too high",
            description=(
                f"Ad spend is {ad_ratio:.1%} of revenue. Reducing to 20% "
                f"would save ${excess:.2f}."
            ),
            estimated_impact=excess,
            confidence=0.65,
            effort="medium",
        ))

    # Platform-level opportunity
    breakdown = ads.get("platform_breakdown", {})
    if len(breakdown) > 1:
        # Find best and worst performing platforms by implied ROAS
        total_conversions = float(ads.get("conversions", 0))
        if total_conversions > 0 and net_revenue > 0:
            rev_per_conversion = net_revenue / total_conversions
            platform_roas = {}
            for platform, spend in breakdown.items():
                if spend > 0:
                    # Proportional estimate
                    plat_share = spend / ad_spend
                    plat_conversions = total_conversions * plat_share
                    plat_revenue = plat_conversions * rev_per_conversion
                    platform_roas[platform] = plat_revenue / spend

            if platform_roas:
                best = max(platform_roas, key=platform_roas.get)
                worst = min(platform_roas, key=platform_roas.get)
                if best != worst:
                    shift_amount = breakdown.get(worst, 0.0) * 0.3
                    opps.append(_make_opportunity(
                        category="advertising",
                        title=f"Reallocate budget from {worst} to {best}",
                        description=(
                            f"Shifting 30% of {worst} budget (${shift_amount:.2f}) "
                            f"to {best} could improve overall ROAS."
                        ),
                        estimated_impact=shift_amount * 0.5,
                        confidence=0.55,
                        effort="low",
                    ))

    return opps


def _detect_cost_reduction_opportunities(
    agg: dict[str, Any],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect cost reduction opportunities."""
    opps: list[dict[str, Any]] = []
    costs = agg.get("costs", {})
    net_revenue = float(metrics.get("net_revenue", 0.0))

    if net_revenue <= 0:
        return opps

    cogs = float(costs.get("cogs", 0.0))
    shipping = float(costs.get("shipping", 0.0))
    platform_fees = float(costs.get("platform_fees", 0.0))

    cogs_ratio = cogs / net_revenue
    shipping_ratio = shipping / net_revenue
    platform_ratio = platform_fees / net_revenue

    if cogs_ratio > _THRESHOLDS["high_cogs_ratio"]:
        savings = (cogs_ratio - 0.50) * net_revenue
        opps.append(_make_opportunity(
            category="cost_reduction",
            title="High COGS ratio — negotiate supplier costs",
            description=(
                f"COGS is {cogs_ratio:.1%} of revenue. Reducing to 50% "
                f"would save ${savings:.2f}."
            ),
            estimated_impact=savings,
            confidence=0.60,
            effort="high",
        ))

    if shipping_ratio > _THRESHOLDS["high_shipping_ratio"]:
        savings = (shipping_ratio - 0.10) * net_revenue
        opps.append(_make_opportunity(
            category="cost_reduction",
            title="High shipping costs — optimize fulfillment",
            description=(
                f"Shipping is {shipping_ratio:.1%} of revenue. Reducing to 10% "
                f"would save ${savings:.2f}."
            ),
            estimated_impact=savings,
            confidence=0.55,
            effort="medium",
        ))

    if platform_ratio > _THRESHOLDS["high_platform_fee_ratio"]:
        savings = (platform_ratio - 0.05) * net_revenue
        opps.append(_make_opportunity(
            category="cost_reduction",
            title="High platform fees — evaluate alternatives",
            description=(
                f"Platform fees are {platform_ratio:.1%} of revenue. "
                f"Reducing to 5% would save ${savings:.2f}."
            ),
            estimated_impact=savings,
            confidence=0.50,
            effort="high",
        ))

    return opps


def _detect_conversion_opportunities(
    agg: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect conversion and funnel optimization opportunities."""
    opps: list[dict[str, Any]] = []
    perf = agg.get("performance", {})
    summary = agg.get("summary", {})

    conversion_rate = float(perf.get("conversion_rate", 0.0))
    cart_abandonment = float(perf.get("cart_abandonment", 0.0))
    return_rate = float(perf.get("return_rate", 0.0))
    total_revenue = float(summary.get("total_revenue", 0.0))

    if conversion_rate > 0 and conversion_rate < _THRESHOLDS["low_conversion"]:
        # Estimate revenue gain from improving conversion
        target = 0.04
        improvement_factor = target / conversion_rate
        potential_revenue = total_revenue * (improvement_factor - 1.0)
        opps.append(_make_opportunity(
            category="conversion",
            title="Low conversion rate — funnel optimization needed",
            description=(
                f"Conversion rate is {conversion_rate:.2%}. Improving to "
                f"4% could add ${potential_revenue:.2f} in revenue."
            ),
            estimated_impact=potential_revenue * 0.15,
            confidence=0.60,
            effort="medium",
        ))

    if cart_abandonment > _THRESHOLDS["high_abandonment"]:
        # Revenue lost to abandonment
        orders = int(summary.get("total_orders", 0))
        aov = float(kpi.get("aov", 0.0))
        if orders > 0 and aov > 0:
            estimated_carts = orders / (1.0 - cart_abandonment) if cart_abandonment < 1.0 else orders
            abandoned = estimated_carts - orders
            recoverable = abandoned * aov * 0.10  # 10% recovery rate
            opps.append(_make_opportunity(
                category="conversion",
                title="High cart abandonment — recovery opportunity",
                description=(
                    f"Cart abandonment is {cart_abandonment:.0%}. Approximately "
                    f"{int(abandoned)} carts abandoned. Recovering 10% could add "
                    f"${recoverable:.2f} in revenue."
                ),
                estimated_impact=recoverable,
                confidence=0.55,
                effort="low",
            ))

    if return_rate > _THRESHOLDS["high_return_rate"]:
        refund_cost = total_revenue * return_rate
        opps.append(_make_opportunity(
            category="conversion",
            title="High return rate — product/description mismatch",
            description=(
                f"Return rate is {return_rate:.1%}. Estimated annual refund "
                f"cost: ${refund_cost:.2f}. Improving descriptions and quality "
                "control could reduce returns."
            ),
            estimated_impact=refund_cost * 0.5,
            confidence=0.50,
            effort="medium",
        ))

    return opps


def _detect_pricing_opportunities(
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect pricing optimization opportunities."""
    opps: list[dict[str, Any]] = []
    aov = float(kpi.get("aov", 0.0))
    profit_per_unit = float(metrics.get("profit_per_unit", 0.0))
    revenue_per_unit = float(metrics.get("revenue_per_unit", 0.0))
    net_revenue = float(metrics.get("net_revenue", 0.0))
    units_sold = int(metrics.get("break_even_units", 0))  # for reference

    if revenue_per_unit > 0 and profit_per_unit > 0:
        margin_per_unit = profit_per_unit / revenue_per_unit
        if margin_per_unit < 0.10:
            price_increase = revenue_per_unit * 0.05
            opps.append(_make_opportunity(
                category="pricing",
                title="Low per-unit margin — consider price increase",
                description=(
                    f"Profit per unit is ${profit_per_unit:.2f} "
                    f"({margin_per_unit:.1%} of unit price). A 5% price "
                    f"increase (${price_increase:.2f}/unit) could improve margins."
                ),
                estimated_impact=net_revenue * 0.05 * 0.7,
                confidence=0.55,
                effort="low",
            ))

    return opps


def _detect_scaling_opportunities(
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect scaling opportunities for profitable operations."""
    opps: list[dict[str, Any]] = []
    net_margin = float(metrics.get("net_margin", 0.0))
    net_profit = float(metrics.get("net_profit", 0.0))
    roas = float(kpi.get("roas", 0.0))
    health_score = float(kpi.get("health_score", 0.0))

    # If business is healthy and profitable, recommend scaling
    if net_margin > 0.15 and roas > 3.0 and health_score > 0.7:
        opps.append(_make_opportunity(
            category="scaling",
            title="Healthy metrics — scale operations",
            description=(
                f"Net margin {net_margin:.1%}, ROAS {roas:.1f}x, health "
                f"score {health_score:.0%}. Business is healthy enough to "
                "scale ad spend and inventory."
            ),
            estimated_impact=net_profit * 0.5,
            confidence=0.60,
            effort="medium",
        ))

    return opps


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_opportunity(
    category: str,
    title: str,
    description: str,
    estimated_impact: float,
    confidence: float,
    effort: str,
) -> dict[str, Any]:
    """Build a standardized Opportunity dict."""
    return {
        "opportunity_id": uuid.uuid4().hex[:10],
        "category": category,
        "title": title,
        "description": description,
        "estimated_impact": round(estimated_impact, 2),
        "confidence": round(confidence, 2),
        "effort": effort,
        "priority": "medium",  # will be overridden by ranking
    }
