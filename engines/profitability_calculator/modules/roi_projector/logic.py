"""ROI decision logic — is this investment worth it?

Takes ROI projections and produces actionable decisions:
- Rank multiple products by ROI
- Determine if a product is worth the time and capital
- Compare against opportunity cost (index funds, other products)
"""
from __future__ import annotations

from typing import Any


# Investment worthiness thresholds
WORTHINESS_THRESHOLDS = {
    "excellent_roi_pct": 200,    # 200%+ annual = excellent
    "good_roi_pct": 100,         # 100%+ = good (doubles money)
    "minimum_roi_pct": 50,       # Below 50% = not worth e-commerce effort
    "sp500_annual_return": 0.10,  # S&P 500 historical average
    "time_value_monthly": 500,    # Opportunity cost of your time per month
}


def compare_product_roi(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank multiple products by projected ROI to prioritize launches.

    Args:
        products: List of ROI projections from code.project_roi(),
                  each augmented with a "product_name" field.

    Returns:
        Ranked list with relative comparison and portfolio recommendation.
    """
    if not products:
        return {"status": "error", "message": "No products to compare"}

    # Score each product
    scored = []
    for product in products:
        name = product.get("product_name", "Unknown")
        roi_summary = product.get("roi_summary", {})
        cash_flow = product.get("cash_flow", {})

        roi_pct = roi_summary.get("roi_pct", 0)
        recovery_month = cash_flow.get("recovery_month")
        monthly_avg = roi_summary.get("monthly_avg_profit", 0)

        # Composite score: ROI weight (50%), cash recovery speed (30%), monthly profit (20%)
        roi_score = min(100, (roi_pct / 300) * 100)  # Cap at 300% ROI
        recovery_score = (
            max(0, 100 - (recovery_month or 13) * 8)  # Faster recovery = higher score
        )
        profit_score = min(100, (monthly_avg / 2000) * 100)  # Cap at $2K/month

        composite = roi_score * 0.50 + recovery_score * 0.30 + profit_score * 0.20

        scored.append({
            "product_name": name,
            "roi_pct": round(roi_pct, 1),
            "recovery_month": recovery_month,
            "monthly_avg_profit": round(monthly_avg, 2),
            "composite_score": round(composite, 1),
            "investment": product.get("total_investment", 0),
        })

    # Sort by composite score descending
    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    # Add rank
    for i, item in enumerate(scored):
        item["rank"] = i + 1

    # Portfolio recommendation
    top_products = [p for p in scored if p["composite_score"] >= 50]
    total_capital_needed = sum(p["investment"] for p in top_products)

    return {
        "rankings": scored,
        "top_pick": scored[0] if scored else None,
        "portfolio": {
            "recommended_products": [p["product_name"] for p in top_products],
            "total_capital_needed": round(total_capital_needed, 2),
            "count": len(top_products),
        },
        "insight": (
            f"Top pick: {scored[0]['product_name']} with {scored[0]['roi_pct']}% ROI. "
            f"{len(top_products)} of {len(scored)} products worth pursuing."
            if scored else "No products to rank."
        ),
    }


def assess_investment_worthiness(roi_data: dict[str, Any]) -> dict[str, Any]:
    """Determine if a product investment is worth the time and capital.

    Considers not just ROI percentage, but also absolute profit, time
    investment, and risk factors.

    Args:
        roi_data: Output from code.project_roi()
    """
    if roi_data.get("status") == "error":
        return {
            "worthy": False,
            "verdict": "reject",
            "score": 0,
            "reasons": [roi_data.get("message", "ROI projection failed")],
        }

    roi_summary = roi_data.get("roi_summary", {})
    cash_flow = roi_data.get("cash_flow", {})
    investment = roi_data.get("total_investment", 0)

    roi_pct = roi_summary.get("roi_pct", 0)
    monthly_avg = roi_summary.get("monthly_avg_profit", 0)
    recovery_month = cash_flow.get("recovery_month")

    score = 0
    reasons = []
    concerns = []

    # ROI percentage check (0-35 points)
    if roi_pct >= WORTHINESS_THRESHOLDS["excellent_roi_pct"]:
        score += 35
        reasons.append(f"Excellent ROI: {roi_pct:.0f}% annual — outstanding return")
    elif roi_pct >= WORTHINESS_THRESHOLDS["good_roi_pct"]:
        score += 25
        reasons.append(f"Good ROI: {roi_pct:.0f}% — more than doubles investment")
    elif roi_pct >= WORTHINESS_THRESHOLDS["minimum_roi_pct"]:
        score += 15
        reasons.append(f"Moderate ROI: {roi_pct:.0f}% — acceptable but not exciting")
    elif roi_pct > 0:
        score += 5
        concerns.append(f"Low ROI: {roi_pct:.0f}% — barely worth the effort vs. passive investing")
    else:
        concerns.append(f"Negative ROI: {roi_pct:.0f}% — this product loses money")

    # Monthly profit viability (0-25 points) — is it worth your time?
    time_value = WORTHINESS_THRESHOLDS["time_value_monthly"]
    if monthly_avg >= time_value * 4:
        score += 25
        reasons.append(f"Strong monthly profit: ${monthly_avg:,.0f}/month")
    elif monthly_avg >= time_value * 2:
        score += 18
        reasons.append(f"Good monthly profit: ${monthly_avg:,.0f}/month")
    elif monthly_avg >= time_value:
        score += 10
        reasons.append(f"Covers time cost: ${monthly_avg:,.0f}/month")
    elif monthly_avg > 0:
        score += 4
        concerns.append(
            f"Monthly profit (${monthly_avg:,.0f}) may not justify time investment"
        )
    else:
        concerns.append("Negative monthly profit on average")

    # Cash recovery speed (0-20 points)
    if recovery_month and recovery_month <= 2:
        score += 20
        reasons.append(f"Very fast cash recovery: month {recovery_month}")
    elif recovery_month and recovery_month <= 4:
        score += 15
        reasons.append(f"Good cash recovery: month {recovery_month}")
    elif recovery_month and recovery_month <= 6:
        score += 8
        reasons.append(f"Slow cash recovery: month {recovery_month}")
    elif recovery_month:
        score += 3
        concerns.append(f"Very slow cash recovery: month {recovery_month}")
    else:
        concerns.append("Cash does not recover within 12 months")

    # Risk-adjusted return (0-20 points)
    # Compare worst-case scenario
    checkpoints = roi_data.get("checkpoints", {})
    day_180_conservative = (
        checkpoints.get("day_180", {}).get("conservative", {}).get("roi_pct", -100)
    )
    if day_180_conservative > 0:
        score += 20
        reasons.append("Profitable even in conservative scenario at 6 months")
    elif day_180_conservative > -25:
        score += 10
        concerns.append("Conservative scenario still slightly negative at 6 months")
    else:
        score += 2
        concerns.append("Conservative scenario shows significant losses at 6 months")

    # Verdict
    if score >= 80:
        verdict = "strong_buy"
        worthy = True
        recommendation = "Excellent investment — proceed with confidence"
    elif score >= 60:
        verdict = "buy"
        worthy = True
        recommendation = "Good investment — proceed with standard risk management"
    elif score >= 40:
        verdict = "hold"
        worthy = True
        recommendation = "Marginal — proceed only if you have a competitive advantage"
    elif score >= 20:
        verdict = "weak"
        worthy = False
        recommendation = "Below threshold — your time is better spent elsewhere"
    else:
        verdict = "reject"
        worthy = False
        recommendation = "Not worth pursuing — look for better opportunities"

    return {
        "worthy": worthy,
        "verdict": verdict,
        "score": min(100, score),
        "recommendation": recommendation,
        "reasons": reasons,
        "concerns": concerns,
    }


def calculate_opportunity_cost(
    roi_data: dict[str, Any],
    alternative_rate: float = 0.10,
) -> dict[str, Any]:
    """Compare this product's ROI against an alternative investment.

    Default alternative is S&P 500 index fund at ~10% annual return.
    Answers: "Is this better than just putting money in an index fund?"

    Args:
        roi_data: Output from code.project_roi()
        alternative_rate: Annual return of alternative investment (default 10%)
    """
    investment = roi_data.get("total_investment", 0)
    roi_summary = roi_data.get("roi_summary", {})
    product_roi_pct = roi_summary.get("roi_pct", 0)

    # Alternative investment returns
    alternative_return = investment * alternative_rate
    product_return = roi_summary.get("total_profit_12m", 0)

    # Excess return (alpha)
    excess_return = product_return - alternative_return
    excess_roi_pct = product_roi_pct - (alternative_rate * 100)

    # Time cost adjustment — e-commerce requires active management
    # Estimate 10-20 hours/month for product management
    hours_per_month = 15
    hourly_rate = 30  # Implicit hourly rate of your time
    annual_time_cost = hours_per_month * hourly_rate * 12
    time_adjusted_return = product_return - annual_time_cost
    time_adjusted_roi = (
        (time_adjusted_return / investment) * 100 if investment > 0 else 0
    )

    # Verdict
    if time_adjusted_roi > alternative_rate * 100:
        verdict = "better_than_alternative"
        message = (
            f"This product returns {product_roi_pct:.0f}% vs. {alternative_rate*100:.0f}% "
            f"from index funds. Even accounting for {hours_per_month}h/month of your time, "
            f"the adjusted ROI ({time_adjusted_roi:.0f}%) beats passive investing."
        )
    elif product_roi_pct > alternative_rate * 100:
        verdict = "marginally_better"
        message = (
            f"Raw ROI ({product_roi_pct:.0f}%) beats index funds ({alternative_rate*100:.0f}%), "
            f"but after accounting for your time, adjusted ROI is {time_adjusted_roi:.0f}%. "
            f"Only worth it if you enjoy the work or can automate operations."
        )
    else:
        verdict = "worse_than_alternative"
        message = (
            f"This product's {product_roi_pct:.0f}% ROI is below index fund returns "
            f"({alternative_rate*100:.0f}%). Your money works harder in passive investments."
        )

    return {
        "product_roi_pct": round(product_roi_pct, 1),
        "alternative_roi_pct": round(alternative_rate * 100, 1),
        "product_return": round(product_return, 2),
        "alternative_return": round(alternative_return, 2),
        "excess_return": round(excess_return, 2),
        "excess_roi_pct": round(excess_roi_pct, 1),
        "time_cost": {
            "hours_per_month": hours_per_month,
            "implicit_hourly_rate": hourly_rate,
            "annual_time_cost": round(annual_time_cost, 2),
        },
        "time_adjusted_roi_pct": round(time_adjusted_roi, 1),
        "verdict": verdict,
        "message": message,
    }
