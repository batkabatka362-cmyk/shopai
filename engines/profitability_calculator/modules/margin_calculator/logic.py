"""Margin decision logic — health assessment, improvement recommendations, scale projections.

Takes raw margin calculations and produces actionable decisions:
- Is this product's margin sustainable?
- What specific actions improve it?
- How do margins change with volume?
"""
from __future__ import annotations

from typing import Any

from .data import get_category_benchmark, get_tier
from .knowledge import get_improvement_playbook


def assess_margin_health(margins: dict[str, Any]) -> dict[str, Any]:
    """Determine whether a product's margins are sustainable.

    Args:
        margins: Dict containing gross_margin_pct, contribution_margin_pct,
                 net_margin_pct, operating_margin_pct, and optionally category.

    Returns:
        Health assessment with verdict, score, and specific concerns.
    """
    gross = margins.get("gross_margin_pct", 0.0)
    contribution = margins.get("contribution_margin_pct", 0.0)
    net = margins.get("net_margin_pct", 0.0)
    operating = margins.get("operating_margin_pct", 0.0)
    category = margins.get("category", "")

    score = 0
    concerns: list[str] = []
    strengths: list[str] = []

    # Contribution margin is the most important signal (0-35 points)
    if contribution >= 40:
        score += 35
        strengths.append(f"Strong contribution margin ({contribution:.1f}%) — healthy unit economics")
    elif contribution >= 25:
        score += 25
        strengths.append(f"Adequate contribution margin ({contribution:.1f}%)")
    elif contribution >= 20:
        score += 15
        concerns.append(f"Thin contribution margin ({contribution:.1f}%) — limited room for error")
    else:
        score += 5
        concerns.append(f"Dangerously low contribution margin ({contribution:.1f}%) — unsustainable")

    # Net margin signals long-term viability (0-25 points)
    if net >= 20:
        score += 25
        strengths.append(f"Excellent net margin ({net:.1f}%) — strong profitability")
    elif net >= 15:
        score += 20
    elif net >= 10:
        score += 12
        concerns.append(f"Net margin ({net:.1f}%) leaves little buffer for unexpected costs")
    else:
        score += 5
        concerns.append(f"Net margin ({net:.1f}%) too low for sustainability")

    # Gross margin as baseline indicator (0-20 points)
    if gross >= 50:
        score += 20
    elif gross >= 35:
        score += 15
    elif gross >= 25:
        score += 8
    else:
        score += 3
        concerns.append(f"Low gross margin ({gross:.1f}%) — COGS too high relative to price")

    # Category comparison (0-20 points)
    if category:
        benchmark = get_category_benchmark(category)
        diff = gross - benchmark["gross"]
        if diff >= 5:
            score += 20
            strengths.append(f"Outperforming category benchmark by {diff:.1f} points")
        elif diff >= -5:
            score += 15
        elif diff >= -15:
            score += 8
            concerns.append(f"Below category benchmark by {abs(diff):.1f} points")
        else:
            score += 3
            concerns.append(f"Far below category benchmark — investigate pricing or COGS")
    else:
        score += 10  # Neutral if no category

    # Verdict
    tier = get_tier(contribution)
    if score >= 80:
        verdict = "excellent"
        summary = "Margins are strong — focus on scaling, not optimizing."
    elif score >= 60:
        verdict = "healthy"
        summary = "Margins are viable — minor improvements possible but not urgent."
    elif score >= 40:
        verdict = "at_risk"
        summary = "Margins are thin — prioritize cost reduction or price increase."
    else:
        verdict = "unsustainable"
        summary = "Margins cannot support a business — fundamental repricing needed."

    return {
        "verdict": verdict,
        "score": min(100, score),
        "tier": tier["tier"],
        "summary": summary,
        "strengths": strengths,
        "concerns": concerns,
    }


def recommend_margin_improvement(
    margins: dict[str, Any],
    breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate specific, prioritized actions to improve margins.

    Args:
        margins: Calculated margin percentages.
        breakdown: Optional cost breakdown with individual cost lines.

    Returns:
        Prioritized list of recommendations with estimated impact.
    """
    contribution = margins.get("contribution_margin_pct", 0.0)
    gross = margins.get("gross_margin_pct", 0.0)
    net = margins.get("net_margin_pct", 0.0)
    price = margins.get("price", 0.0)
    cogs = margins.get("cogs", 0.0)

    recommendations: list[dict[str, Any]] = []

    # Check COGS ratio — if COGS > 60% of price, that is the problem
    if price > 0 and cogs / price > 0.60:
        recommendations.append({
            "priority": 1,
            "action": "Reduce COGS or raise price — COGS is {:.0f}% of price".format(cogs / price * 100),
            "estimated_impact": "10-20% gross margin improvement",
            "approach": "Get 3 competing supplier quotes. Target landed COGS under 40% of price.",
        })

    # Check if variable costs are eating the gap between gross and contribution
    variable_gap = gross - contribution
    if variable_gap > 15:
        recommendations.append({
            "priority": 1,
            "action": f"Variable costs are eating {variable_gap:.1f} points between gross and contribution",
            "estimated_impact": "5-15% contribution margin improvement",
            "approach": "Audit transaction fees, packaging, and per-order costs. "
                        "Negotiate payment processing rates at volume.",
        })

    # Check ad spend pressure
    ad_spend_pct = margins.get("ad_spend_pct_of_revenue", 0)
    if ad_spend_pct > 25:
        recommendations.append({
            "priority": 2,
            "action": f"Ad spend at {ad_spend_pct:.1f}% of revenue — too high",
            "estimated_impact": "5-10% operating margin improvement",
            "approach": "Set minimum ROAS target at {:.1f}x. Cut underperforming campaigns.".format(
                100 / contribution if contribution > 0 else 3.0
            ),
        })

    # Price increase opportunity
    if contribution < 40 and price > 0:
        new_price = price * 1.10
        new_gross_pct = (new_price - cogs) / new_price * 100 if new_price > 0 else 0
        recommendations.append({
            "priority": 2,
            "action": "Test 10% price increase (${:.2f} -> ${:.2f})".format(price, new_price),
            "estimated_impact": "~{:.1f}% gross margin (up from {:.1f}%)".format(new_gross_pct, gross),
            "approach": "A/B test on 20% of traffic for 2 weeks. "
                        "If conversion drops less than 5%, adopt the new price.",
        })

    # Add playbook items not already covered
    playbook = get_improvement_playbook(contribution)
    existing_actions = {r["action"][:20] for r in recommendations}
    for item in playbook:
        if item["action"][:20] not in existing_actions and len(recommendations) < 7:
            recommendations.append({
                "priority": 3,
                "action": item["action"],
                "estimated_impact": item["impact"],
                "approach": item["detail"],
            })

    recommendations.sort(key=lambda r: r["priority"])

    return {
        "current_contribution_margin": contribution,
        "target_contribution_margin": max(contribution + 10, 30.0),
        "recommendations": recommendations,
        "urgency": "critical" if contribution < 20 else "moderate" if contribution < 35 else "low",
    }


def calculate_margin_at_scale(
    margins: dict[str, Any],
    volume_tiers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Project how margins improve at different volume levels.

    Volume affects: COGS (bulk discounts), shipping (rate tiers),
    fixed cost allocation, and supplier negotiation power.

    Args:
        margins: Current margin data including price, cogs, and cost lines.
        volume_tiers: Monthly unit volumes to project. Defaults to standard tiers.

    Returns:
        List of projections, one per volume tier.
    """
    if volume_tiers is None:
        volume_tiers = [50, 100, 250, 500, 1000, 2500, 5000]

    price = margins.get("price", 0.0)
    cogs = margins.get("cogs", 0.0)
    variable_costs_per_unit = margins.get("variable_costs_per_unit", 0.0)
    fixed_costs_monthly = margins.get("fixed_costs_monthly", 500.0)

    if price <= 0:
        return []

    projections: list[dict[str, Any]] = []
    for volume in volume_tiers:
        # COGS discount curve: 0% at 50, ~5% at 500, ~12% at 2500, ~18% at 5000
        if volume >= 2500:
            cogs_discount = 0.12 + (volume - 2500) / 2500 * 0.06
        elif volume >= 500:
            cogs_discount = 0.05 + (volume - 500) / 2000 * 0.07
        elif volume >= 100:
            cogs_discount = 0.01 + (volume - 100) / 400 * 0.04
        else:
            cogs_discount = 0.0
        cogs_discount = min(cogs_discount, 0.20)  # Cap at 20%

        # Shipping discount: improves ~15% at 500+ units (pallet vs parcel)
        shipping_discount = min(0.15, volume / 5000 * 0.15) if volume >= 100 else 0.0

        adj_cogs = cogs * (1 - cogs_discount)
        adj_variable = variable_costs_per_unit * (1 - shipping_discount * 0.5)
        fixed_per_unit = fixed_costs_monthly / max(volume, 1)

        gross_margin = (price - adj_cogs) / price * 100
        contribution_margin = (price - adj_cogs - adj_variable) / price * 100
        net_margin = (price - adj_cogs - adj_variable - fixed_per_unit) / price * 100

        monthly_revenue = price * volume
        monthly_profit = (price - adj_cogs - adj_variable - fixed_per_unit) * volume

        projections.append({
            "volume": volume,
            "adjusted_cogs": round(adj_cogs, 2),
            "cogs_discount_pct": round(cogs_discount * 100, 1),
            "gross_margin_pct": round(gross_margin, 1),
            "contribution_margin_pct": round(contribution_margin, 1),
            "net_margin_pct": round(net_margin, 1),
            "monthly_revenue": round(monthly_revenue, 2),
            "monthly_profit": round(monthly_profit, 2),
            "fixed_cost_per_unit": round(fixed_per_unit, 2),
        })

    return projections
