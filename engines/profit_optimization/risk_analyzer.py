"""Profit Optimization Engine — risk analyzer.

Analyzes the risk of each optimization: financial downside, customer
impact, and competitive response. Produces a risk assessment with
mitigations.

Model note: Would use Mistral for risk analysis and decision logic.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Risk profiles by optimization action type
# ---------------------------------------------------------------------------

_RISK_PROFILES: dict[str, dict[str, Any]] = {
    "emergency_cost_reduction": {
        "financial_base": 0.3,
        "customer_base": 0.4,
        "competitive_base": 0.2,
        "mitigations": [
            "Phase cost cuts over 2-4 weeks to monitor impact",
            "Protect customer-facing quality during cuts",
            "Maintain minimum ad spend on proven campaigns",
        ],
    },
    "margin_improvement": {
        "financial_base": 0.2,
        "customer_base": 0.3,
        "competitive_base": 0.3,
        "mitigations": [
            "Test price changes on a subset of products first",
            "Monitor conversion rate daily after changes",
            "Prepare rollback plan if conversion drops >10%",
        ],
    },
    "scale_ad_budget": {
        "financial_base": 0.4,
        "customer_base": 0.1,
        "competitive_base": 0.3,
        "mitigations": [
            "Set daily ROAS kill-switch threshold at 1.5x",
            "Increase budget incrementally (10% per week)",
            "Diversify across platforms to reduce single-point risk",
        ],
    },
    "reallocate_ad_budget": {
        "financial_base": 0.2,
        "customer_base": 0.1,
        "competitive_base": 0.2,
        "mitigations": [
            "Shift budget gradually (30% at a time)",
            "Keep minimum viable spend on secondary platforms",
            "Monitor attribution carefully during transition",
        ],
    },
    "optimize_ad_campaigns": {
        "financial_base": 0.2,
        "customer_base": 0.1,
        "competitive_base": 0.2,
        "mitigations": [
            "Pause lowest performers first, not all at once",
            "A/B test new creative before full rollout",
            "Maintain retargeting campaigns during optimization",
        ],
    },
    "negotiate_supplier_costs": {
        "financial_base": 0.1,
        "customer_base": 0.2,
        "competitive_base": 0.1,
        "mitigations": [
            "Keep backup suppliers identified before negotiation",
            "Ensure quality specifications are in contract",
            "Phase in new suppliers with trial orders",
        ],
    },
    "optimize_shipping": {
        "financial_base": 0.1,
        "customer_base": 0.3,
        "competitive_base": 0.1,
        "mitigations": [
            "Test new carriers with non-urgent orders first",
            "Monitor delivery times and customer complaints",
            "Keep premium shipping option for high-value orders",
        ],
    },
    "reduce_platform_costs": {
        "financial_base": 0.3,
        "customer_base": 0.2,
        "competitive_base": 0.1,
        "mitigations": [
            "Run platforms in parallel during migration period",
            "Migrate lowest-risk products first",
            "Maintain SEO rankings during transition",
        ],
    },
    "cart_recovery_campaign": {
        "financial_base": 0.05,
        "customer_base": 0.15,
        "competitive_base": 0.05,
        "mitigations": [
            "Limit discount offers to prevent margin erosion",
            "Cap email frequency to avoid spam complaints",
            "A/B test email subject lines and timing",
        ],
    },
    "funnel_optimization": {
        "financial_base": 0.1,
        "customer_base": 0.15,
        "competitive_base": 0.05,
        "mitigations": [
            "A/B test all changes before full rollout",
            "Keep original design as control variant",
            "Monitor bounce rate and exit pages after changes",
        ],
    },
    "reduce_returns": {
        "financial_base": 0.05,
        "customer_base": 0.1,
        "competitive_base": 0.05,
        "mitigations": [
            "Improve descriptions without over-promising",
            "Implement quality checks gradually",
            "Track customer satisfaction alongside return rate",
        ],
    },
    "strategic_price_increase": {
        "financial_base": 0.3,
        "customer_base": 0.5,
        "competitive_base": 0.4,
        "mitigations": [
            "Test on 10-20% of catalog before broad rollout",
            "Monitor competitor pricing weekly",
            "Add value (bundling, service) to justify increase",
            "Prepare discount fallback for price-sensitive segments",
        ],
    },
    "scale_operations": {
        "financial_base": 0.4,
        "customer_base": 0.2,
        "competitive_base": 0.3,
        "mitigations": [
            "Scale in phases with clear success metrics per phase",
            "Maintain cash reserve for at least 2 months of burn",
            "Set maximum spend limits per channel",
        ],
    },
}

_DEFAULT_PROFILE: dict[str, Any] = {
    "financial_base": 0.3,
    "customer_base": 0.3,
    "competitive_base": 0.3,
    "mitigations": [
        "Test changes incrementally",
        "Monitor key metrics daily",
        "Prepare rollback plan",
    ],
}


def analyze_risks(
    optimizations: list[dict[str, Any]],
    aggregated: dict[str, Any],
    profit_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Analyze risk for each optimization.

    Each risk is computed from base profile adjusted by current financial
    health — riskier when margins are thin or business is unprofitable.

    Args:
        optimizations: List of Optimization dicts.
        aggregated: Output from data_aggregator.
        profit_metrics: Output from profit_calculator.

    Returns:
        Structured dict with list of RiskAssessment dicts.
    """
    try:
        opts = copy.deepcopy(optimizations)
        metrics = copy.deepcopy(profit_metrics)

        # Financial health modifier: thin margins = higher risk
        net_margin = float(metrics.get("net_margin", 0.0))
        net_profit = float(metrics.get("net_profit", 0.0))

        if net_margin < 0:
            health_modifier = 0.20  # add 20% risk when unprofitable
        elif net_margin < 0.05:
            health_modifier = 0.10
        elif net_margin < 0.10:
            health_modifier = 0.05
        else:
            health_modifier = 0.0

        assessments: list[dict[str, Any]] = []
        for opt in opts:
            assessment = _assess_single(opt, health_modifier)
            assessments.append(assessment)

        return {
            "status": "success",
            "assessments": assessments,
            "count": len(assessments),
        }
    except Exception as exc:
        return {
            "status": "error",
            "assessments": [],
            "count": 0,
            "error": f"Risk analysis failed: {exc}",
        }


def _assess_single(
    opt: dict[str, Any],
    health_modifier: float,
) -> dict[str, Any]:
    """Assess risk for a single optimization."""
    action = opt.get("action", "")
    profile = _RISK_PROFILES.get(action, _DEFAULT_PROFILE)

    financial = min(float(profile["financial_base"]) + health_modifier, 1.0)
    customer = min(float(profile["customer_base"]) + health_modifier * 0.5, 1.0)
    competitive = float(profile["competitive_base"])

    # Overall risk: weighted average
    overall = financial * 0.45 + customer * 0.30 + competitive * 0.25

    # Cost change amplifies financial risk
    cost_change = float(opt.get("expected_cost_change", 0.0))
    if cost_change > 0:
        # Spending more money = slightly higher risk
        overall = min(overall + 0.05, 1.0)

    risk_level = _risk_score_to_level(overall)

    return {
        "optimization_id": opt.get("optimization_id", ""),
        "financial_risk": round(financial, 2),
        "customer_impact_risk": round(customer, 2),
        "competitive_risk": round(competitive, 2),
        "overall_risk": round(overall, 2),
        "risk_level": risk_level,
        "mitigations": list(profile.get("mitigations", [])),
        "model_note": "Mistral: risk analysis and decision logic",
    }


def _risk_score_to_level(score: float) -> str:
    """Convert a 0-1 risk score to a label."""
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    if score >= 0.2:
        return "low"
    return "minimal"
