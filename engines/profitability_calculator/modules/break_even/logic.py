"""Break-even decision logic — is this launch feasible?

Takes break-even calculations and produces actionable recommendations:
- Is break-even achievable within acceptable timeframe?
- What launch budget makes sense?
- How long until investment pays back?
"""
from __future__ import annotations

from typing import Any


# Feasibility thresholds
FEASIBILITY_THRESHOLDS = {
    "excellent_days": 30,
    "good_days": 60,
    "acceptable_days": 90,
    "max_days": 180,
    "min_contribution_margin_pct": 20.0,
    "max_initial_investment_test": 5000,
    "ideal_batch_buffer_pct": 1.20,  # First batch should be 120% of break-even
}


def assess_break_even_feasibility(analysis: dict[str, Any]) -> dict[str, Any]:
    """Determine if break-even is achievable and rate the launch risk.

    Args:
        analysis: Output from code.calculate_break_even()

    Returns:
        Feasibility verdict with score, risk level, and recommendations.
    """
    if analysis.get("status") == "error":
        return {
            "feasible": False,
            "verdict": "no_go",
            "score": 0,
            "risk_level": "critical",
            "reasons": [analysis.get("message", "Negative margin")],
            "recommendations": [analysis.get("recommendation", "Fix pricing")],
        }

    be = analysis["break_even"]
    margin = analysis["contribution_margin"]
    first_batch = analysis.get("first_batch", {})
    total_fixed = analysis.get("total_fixed_costs", 0)

    score = 0
    reasons = []
    recommendations = []

    # Timeline scoring (0-35 points)
    be_days = be["days"]
    if be_days <= FEASIBILITY_THRESHOLDS["excellent_days"]:
        score += 35
        reasons.append(f"Fast break-even: {be_days:.0f} days — excellent")
    elif be_days <= FEASIBILITY_THRESHOLDS["good_days"]:
        score += 25
        reasons.append(f"Reasonable break-even: {be_days:.0f} days")
    elif be_days <= FEASIBILITY_THRESHOLDS["acceptable_days"]:
        score += 15
        reasons.append(f"Slow break-even: {be_days:.0f} days — manageable but tight")
    elif be_days <= FEASIBILITY_THRESHOLDS["max_days"]:
        score += 5
        reasons.append(f"Very slow break-even: {be_days:.0f} days — high risk")
        recommendations.append("Reduce launch costs or increase price to shorten timeline")
    else:
        reasons.append(f"Break-even at {be_days:.0f} days exceeds 6-month limit — do not launch")
        recommendations.append("Fundamentally rethink pricing, costs, or product viability")

    # Margin quality scoring (0-30 points)
    margin_pct = margin["margin_pct"]
    if margin_pct >= 50:
        score += 30
        reasons.append(f"Strong margin: {margin_pct:.1f}% — healthy buffer for errors")
    elif margin_pct >= 35:
        score += 22
        reasons.append(f"Good margin: {margin_pct:.1f}%")
    elif margin_pct >= FEASIBILITY_THRESHOLDS["min_contribution_margin_pct"]:
        score += 12
        reasons.append(f"Thin margin: {margin_pct:.1f}% — limited room for discounts/errors")
        recommendations.append("Negotiate lower COGS or reduce variable costs")
    else:
        score += 3
        reasons.append(f"Dangerously thin margin: {margin_pct:.1f}%")
        recommendations.append("Margin too low — any small cost increase wipes out profit")

    # Investment size scoring (0-20 points)
    if total_fixed <= 2000:
        score += 20
        reasons.append(f"Low investment (${total_fixed:,.0f}) — minimal risk")
    elif total_fixed <= FEASIBILITY_THRESHOLDS["max_initial_investment_test"]:
        score += 15
        reasons.append(f"Moderate investment (${total_fixed:,.0f}) — within test budget")
    elif total_fixed <= 10000:
        score += 8
        reasons.append(f"Significant investment (${total_fixed:,.0f}) — ensure conviction")
        recommendations.append("Consider starting with smaller first batch to reduce risk")
    else:
        score += 2
        reasons.append(f"Large investment (${total_fixed:,.0f}) — high stakes launch")
        recommendations.append("Validate demand before committing this much capital")

    # First batch coverage (0-15 points)
    if first_batch.get("covers_break_even"):
        surplus = first_batch.get("surplus_units", 0)
        score += 15
        reasons.append(f"First batch covers break-even with {surplus} surplus units")
    else:
        score += 3
        recommendations.append(
            "First batch does not cover break-even — you'll need to reorder before profitability"
        )

    # Verdict
    if score >= 80:
        verdict, risk = "strong_go", "low"
    elif score >= 60:
        verdict, risk = "go", "moderate"
    elif score >= 40:
        verdict, risk = "conditional_go", "elevated"
    elif score >= 20:
        verdict, risk = "risky", "high"
    else:
        verdict, risk = "no_go", "critical"

    return {
        "feasible": score >= 40,
        "verdict": verdict,
        "score": min(100, score),
        "risk_level": risk,
        "break_even_days": be_days,
        "total_investment": total_fixed,
        "reasons": reasons,
        "recommendations": recommendations,
    }


def recommend_launch_budget(break_even: dict[str, Any]) -> dict[str, Any]:
    """Recommend an optimal launch budget based on break-even analysis.

    Balances cost minimization with adequate marketing for launch velocity.

    Args:
        break_even: Output from code.calculate_break_even()
    """
    if break_even.get("status") == "error":
        return {"status": "error", "message": "Cannot recommend budget — fix margins first"}

    total_fixed = break_even.get("total_fixed_costs", 0)
    fixed_costs = break_even.get("fixed_costs", {})
    be_days = break_even["break_even"]["days"]
    margin_per_unit = break_even["contribution_margin"]["per_unit"]
    daily_sales = break_even.get("daily_sales_estimate", 1.0)

    # Marketing should be 30-50% of total launch budget, not more
    current_marketing = fixed_costs.get("marketing_launch_budget", 0)
    marketing_pct = (current_marketing / total_fixed * 100) if total_fixed > 0 else 0

    recommendations = {}

    # Conservative budget (minimize risk)
    conservative_marketing = min(current_marketing, total_fixed * 0.25)
    conservative_total = total_fixed - current_marketing + conservative_marketing
    recommendations["conservative"] = {
        "total_budget": round(conservative_total, 2),
        "marketing_budget": round(conservative_marketing, 2),
        "break_even_days": round(
            (conservative_total / margin_per_unit) / max(daily_sales * 0.7, 0.1), 1
        ),
        "description": "Minimal marketing — slower ramp but less capital at risk",
    }

    # Recommended budget (balanced)
    recommended_marketing = total_fixed * 0.35
    recommended_total = total_fixed - current_marketing + recommended_marketing
    recommendations["recommended"] = {
        "total_budget": round(recommended_total, 2),
        "marketing_budget": round(recommended_marketing, 2),
        "break_even_days": round(be_days, 1),
        "description": "Balanced approach — adequate marketing with controlled spend",
    }

    # Aggressive budget (faster break-even)
    aggressive_marketing = total_fixed * 0.50
    aggressive_total = total_fixed - current_marketing + aggressive_marketing
    boosted_daily_sales = daily_sales * 1.5  # More ads = more velocity
    recommendations["aggressive"] = {
        "total_budget": round(aggressive_total, 2),
        "marketing_budget": round(aggressive_marketing, 2),
        "break_even_days": round(
            (aggressive_total / margin_per_unit) / max(boosted_daily_sales, 0.1), 1
        ),
        "description": "Heavy marketing push — faster velocity but higher burn",
    }

    return {
        "current_budget": round(total_fixed, 2),
        "marketing_share_pct": round(marketing_pct, 1),
        "recommendations": recommendations,
        "insight": (
            "Marketing over 50% of launch budget is usually wasteful for new products. "
            "Focus on organic channels (SEO, content) after initial paid push."
        ),
    }


def calculate_payback_period(
    investment: float,
    monthly_profit: float,
    growth_rate: float = 0.10,
) -> dict[str, Any]:
    """Calculate how many months until total investment is recovered.

    Unlike break-even (which covers launch costs), payback period considers
    the full investment including inventory reorders and ongoing costs.

    Args:
        investment: Total capital deployed (not just launch costs)
        monthly_profit: Net monthly profit after all costs
        growth_rate: Monthly profit growth rate (default 10% — new store ramp)
    """
    if monthly_profit <= 0:
        return {
            "payback_months": None,
            "status": "unprofitable",
            "message": "Monthly profit is zero or negative — payback not possible",
        }

    cumulative_profit = 0.0
    current_monthly = monthly_profit
    month = 0
    monthly_breakdown = []

    while cumulative_profit < investment and month < 36:
        month += 1
        cumulative_profit += current_monthly
        monthly_breakdown.append({
            "month": month,
            "monthly_profit": round(current_monthly, 2),
            "cumulative_profit": round(cumulative_profit, 2),
            "remaining": round(max(0, investment - cumulative_profit), 2),
        })
        current_monthly *= (1 + growth_rate)

    if cumulative_profit >= investment:
        return {
            "payback_months": month,
            "status": "achievable",
            "total_profit_at_payback": round(cumulative_profit, 2),
            "investment": round(investment, 2),
            "monthly_breakdown": monthly_breakdown,
            "summary": f"Investment of ${investment:,.0f} recovered in {month} months",
        }

    return {
        "payback_months": None,
        "status": "too_long",
        "message": f"Investment not recovered within 36 months (accumulated ${cumulative_profit:,.0f})",
        "investment": round(investment, 2),
        "shortfall": round(investment - cumulative_profit, 2),
    }
