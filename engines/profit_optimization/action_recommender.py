"""Profit Optimization Engine — action recommender.

Produces concrete, prioritized action recommendations with expected
impact, implementation steps, and timeframes.

Model note: Would use LLaMA for creative optimization ideas
(offers, pricing angles, marketing copy).
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


def recommend_actions(
    selected_strategy: dict[str, Any],
    optimizations: list[dict[str, Any]],
    risk_assessments: list[dict[str, Any]],
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Generate concrete action recommendations from the selected strategy.

    Maps each optimization in the strategy to a human-readable action
    with clear steps, expected impact, and priority.

    Args:
        selected_strategy: Output from strategy_selector.
        optimizations: Full list of Optimization dicts.
        risk_assessments: List of RiskAssessment dicts.
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.

    Returns:
        Structured dict with list of ActionRecommendation dicts.
    """
    try:
        strategy = copy.deepcopy(selected_strategy)
        opts = copy.deepcopy(optimizations)
        risks = copy.deepcopy(risk_assessments)
        metrics = copy.deepcopy(profit_metrics)

        selected_ids = set(strategy.get("optimization_ids", []))
        risk_map = {
            r["optimization_id"]: r
            for r in risks
            if "optimization_id" in r
        }

        # Build actions from selected optimizations
        actions: list[dict[str, Any]] = []
        for opt in opts:
            if opt.get("optimization_id") not in selected_ids:
                continue

            action = _build_action(opt, risk_map, metrics)
            actions.append(action)

        # Sort by priority weight then by expected impact
        priority_weight = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(key=lambda a: (
            priority_weight.get(a.get("priority", "medium"), 2),
            -float(a.get("expected_impact", 0.0)),
        ))

        return {
            "status": "success",
            "actions": actions,
            "count": len(actions),
        }
    except Exception as exc:
        return {
            "status": "error",
            "actions": [],
            "count": 0,
            "error": f"Action recommendation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Action builders
# ---------------------------------------------------------------------------

_ACTION_TEMPLATES: dict[str, dict[str, Any]] = {
    "emergency_cost_reduction": {
        "title": "Emergency Cost Reduction",
        "category": "cost",
        "steps": [
            "Audit all cost line items and identify top 3 by spend",
            "Pause underperforming ad campaigns immediately",
            "Contact top suppliers to renegotiate terms",
            "Review and eliminate non-essential tool subscriptions",
            "Set cost-reduction targets for each category",
        ],
    },
    "margin_improvement": {
        "title": "Improve Profit Margins",
        "category": "margin",
        "steps": [
            "Analyze margin by product to identify low-margin items",
            "Test 3-5% price increase on top-selling products",
            "Negotiate bulk discounts with suppliers",
            "Optimize shipping by comparing carrier rates",
            "Monitor customer response to pricing changes",
        ],
    },
    "scale_ad_budget": {
        "title": "Scale Advertising Budget",
        "category": "growth",
        "steps": [
            "Identify top-performing ad sets by ROAS",
            "Increase budget by 20-30% on proven campaigns",
            "Launch lookalike audiences based on best converters",
            "Set up daily ROAS monitoring with kill switch at 1.5x",
            "Review results after 7 days and adjust",
        ],
    },
    "reallocate_ad_budget": {
        "title": "Reallocate Ad Budget Across Platforms",
        "category": "advertising",
        "steps": [
            "Pull per-platform ROAS and CPA data for last 30 days",
            "Shift 30% of worst-platform budget to best platform",
            "Create new campaigns on best platform with shifted budget",
            "Monitor per-platform metrics daily for 2 weeks",
            "Continue shifting if results confirm improvement",
        ],
    },
    "optimize_ad_campaigns": {
        "title": "Optimize Ad Campaigns for Efficiency",
        "category": "advertising",
        "steps": [
            "Pause all ad sets with ROAS below 1.0x",
            "Consolidate audiences to reduce overlap",
            "Refresh ad creative (new images, copy angles)",
            "Implement bid caps to control CPA",
            "A/B test new audiences and landing pages",
        ],
    },
    "negotiate_supplier_costs": {
        "title": "Negotiate Lower Supplier Costs",
        "category": "cost",
        "steps": [
            "Get quotes from 3 alternative suppliers",
            "Prepare volume commitment offer for current supplier",
            "Negotiate payment terms (net-30 for discount)",
            "Evaluate drop-shipping for slow-moving SKUs",
            "Document new terms and projected savings",
        ],
    },
    "optimize_shipping": {
        "title": "Optimize Shipping and Fulfillment",
        "category": "cost",
        "steps": [
            "Compare rates across 3+ carriers for common package sizes",
            "Evaluate 3PL options if handling in-house",
            "Implement dimensional weight optimization",
            "Offer free shipping threshold to increase AOV",
            "Negotiate volume rates with preferred carrier",
        ],
    },
    "reduce_platform_costs": {
        "title": "Reduce Platform Fees",
        "category": "cost",
        "steps": [
            "Review current platform fee structure in detail",
            "Compare fees with alternative platforms",
            "Negotiate enterprise or volume discounts",
            "Evaluate building owned sales channel to reduce dependency",
            "Calculate break-even for platform migration",
        ],
    },
    "cart_recovery_campaign": {
        "title": "Launch Cart Abandonment Recovery",
        "category": "conversion",
        "steps": [
            "Set up 3-email cart abandonment sequence",
            "Email 1: Reminder (1 hour after abandonment)",
            "Email 2: Social proof + urgency (24 hours)",
            "Email 3: Small discount offer (48 hours)",
            "Add exit-intent popup with discount code",
            "Track recovery rate and adjust discount level",
        ],
    },
    "funnel_optimization": {
        "title": "Optimize Conversion Funnel",
        "category": "conversion",
        "steps": [
            "Audit current funnel with analytics to find drop-off points",
            "A/B test product page layout and CTAs",
            "Simplify checkout to reduce friction",
            "Add trust signals (reviews, guarantees, security badges)",
            "Optimize page load speed (target under 3 seconds)",
        ],
    },
    "reduce_returns": {
        "title": "Reduce Product Return Rate",
        "category": "quality",
        "steps": [
            "Analyze return reasons by category",
            "Improve product photos and descriptions for accuracy",
            "Add sizing guides and comparison charts",
            "Implement pre-purchase Q&A or live chat",
            "Tighten quality control on outgoing shipments",
        ],
    },
    "strategic_price_increase": {
        "title": "Implement Strategic Price Increase",
        "category": "pricing",
        "steps": [
            "Identify products with inelastic demand (high repeat purchase)",
            "Test 3-5% price increase on those products first",
            "Monitor conversion rate daily for 2 weeks",
            "If conversion holds, expand to more products",
            "Use value-add bundling to justify higher prices",
        ],
    },
    "scale_operations": {
        "title": "Scale Profitable Operations",
        "category": "growth",
        "steps": [
            "Allocate 30% of net profit to growth reinvestment",
            "Increase ad spend on proven campaigns",
            "Expand product catalog with high-margin items",
            "Optimize supply chain for higher volume",
            "Set monthly growth targets and review cadence",
        ],
    },
}


def _build_action(
    opt: dict[str, Any],
    risk_map: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Build an ActionRecommendation from an optimization."""
    action_key = opt.get("action", "general_optimization")
    template = _ACTION_TEMPLATES.get(action_key, {})

    # Determine priority based on profit change and effort
    profit_change = float(opt.get("expected_profit_change", 0.0))
    effort = opt.get("implementation_effort", "medium")
    priority = _compute_priority(profit_change, effort, risk_map.get(opt["optimization_id"]))

    title = template.get("title", action_key.replace("_", " ").title())
    category = template.get("category", "general")
    steps = template.get("steps", [opt.get("details", "Execute optimization.")])

    return {
        "action_id": uuid.uuid4().hex[:10],
        "title": title,
        "description": opt.get("details", ""),
        "priority": priority,
        "expected_impact": round(profit_change, 2),
        "category": category,
        "steps": steps,
        "timeframe": opt.get("timeframe", "2-4 weeks"),
        "model_note": "LLaMA: creative optimization recommendations",
    }


def _compute_priority(
    profit_change: float,
    effort: str,
    risk: dict[str, Any] | None,
) -> str:
    """Compute action priority from impact, effort, and risk."""
    score = 0.0

    # Impact scoring
    if profit_change > 1000:
        score += 3
    elif profit_change > 500:
        score += 2
    elif profit_change > 100:
        score += 1

    # Effort bonus (easier = higher priority)
    effort_bonus = {"low": 2, "medium": 1, "high": 0}
    score += effort_bonus.get(effort, 1)

    # Risk penalty
    if risk:
        overall_risk = float(risk.get("overall_risk", 0.5))
        if overall_risk > 0.7:
            score -= 1

    if score >= 4:
        return "critical"
    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    return "low"
