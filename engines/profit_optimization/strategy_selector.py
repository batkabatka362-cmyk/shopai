"""Profit Optimization Engine — strategy selector.

Selects the best strategy from generated optimizations by evaluating
four archetypes: maximize margin, scale revenue, reduce costs, or
balanced growth. Picks the one that best fits current metrics and risk.

Model note: Would use Mistral for decision logic.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Strategy archetypes
# ---------------------------------------------------------------------------

_ARCHETYPES = {
    "maximize_margin": {
        "name": "Maximize Margin",
        "description": "Focus on improving profit margins through pricing and cost control.",
        "preferred_actions": {
            "strategic_price_increase", "margin_improvement",
            "negotiate_supplier_costs", "reduce_platform_costs",
            "emergency_cost_reduction",
        },
    },
    "scale_revenue": {
        "name": "Scale Revenue",
        "description": "Focus on growing top-line revenue through ad scaling and conversion.",
        "preferred_actions": {
            "scale_ad_budget", "scale_operations",
            "funnel_optimization", "cart_recovery_campaign",
            "reallocate_ad_budget",
        },
    },
    "reduce_costs": {
        "name": "Reduce Costs",
        "description": "Focus on cutting costs across operations, ads, and supply chain.",
        "preferred_actions": {
            "optimize_ad_campaigns", "negotiate_supplier_costs",
            "optimize_shipping", "reduce_platform_costs",
            "emergency_cost_reduction", "reduce_returns",
        },
    },
    "balanced_growth": {
        "name": "Balanced Growth",
        "description": "Balanced approach: moderate cost optimization with careful scaling.",
        "preferred_actions": set(),  # accepts all
    },
}


def select_strategy(
    optimizations: list[dict[str, Any]],
    risk_assessments: list[dict[str, Any]],
    profit_metrics: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, Any]:
    """Select the best strategy given current optimizations and metrics.

    Scores each archetype by how well it fits the business situation,
    then picks the highest-scoring one and maps relevant optimizations.

    Args:
        optimizations: List of Optimization dicts.
        risk_assessments: List of RiskAssessment dicts.
        profit_metrics: Output from profit_calculator.
        kpis: Output from kpi_analyzer.

    Returns:
        Structured dict with the selected Strategy.
    """
    try:
        opts = copy.deepcopy(optimizations)
        risks = copy.deepcopy(risk_assessments)
        metrics = copy.deepcopy(profit_metrics)
        kpi = copy.deepcopy(kpis)

        if not opts:
            return {
                "status": "success",
                "strategy": _empty_strategy("No optimizations available"),
            }

        # Score each archetype
        archetype_scores: dict[str, float] = {}
        archetype_reasoning: dict[str, list[str]] = {}

        for key, archetype in _ARCHETYPES.items():
            score, reasons = _score_archetype(key, opts, risks, metrics, kpi)
            archetype_scores[key] = score
            archetype_reasoning[key] = reasons

        # Pick the best archetype
        best_key = max(archetype_scores, key=archetype_scores.get)
        best_archetype = _ARCHETYPES[best_key]

        # Select optimizations that fit this strategy
        preferred = best_archetype["preferred_actions"]
        if preferred:
            selected_opts = [
                o for o in opts if o.get("action", "") in preferred
            ]
            # Also include high-impact opts even if not in preferred set
            remaining = [o for o in opts if o not in selected_opts]
            remaining.sort(
                key=lambda o: float(o.get("expected_profit_change", 0.0)),
                reverse=True,
            )
            selected_opts.extend(remaining[:2])
        else:
            # Balanced: take top optimizations by profit impact
            selected_opts = sorted(
                opts,
                key=lambda o: float(o.get("expected_profit_change", 0.0)),
                reverse=True,
            )[:5]

        # Compute aggregated expected changes
        total_profit_change = sum(
            float(o.get("expected_profit_change", 0.0)) for o in selected_opts
        )
        total_revenue_change = sum(
            float(o.get("expected_revenue_change", 0.0)) for o in selected_opts
        )

        # Risk level from assessments
        risk_level = _compute_strategy_risk(selected_opts, risks)

        # Confidence based on archetype score and risk
        base_confidence = min(archetype_scores[best_key] / 100.0, 0.95)
        risk_penalty = {"low": 0.0, "medium": 0.10, "high": 0.25}.get(risk_level, 0.15)
        confidence = max(round(base_confidence - risk_penalty, 2), 0.10)

        strategy: dict[str, Any] = {
            "strategy_id": uuid.uuid4().hex[:10],
            "name": best_archetype["name"],
            "description": best_archetype["description"],
            "optimization_ids": [o["optimization_id"] for o in selected_opts],
            "expected_total_profit_change": round(total_profit_change, 2),
            "expected_total_revenue_change": round(total_revenue_change, 2),
            "risk_level": risk_level,
            "confidence": confidence,
            "reasoning": archetype_reasoning.get(best_key, []),
        }

        return {
            "status": "success",
            "strategy": strategy,
        }
    except Exception as exc:
        return {
            "status": "error",
            "strategy": _empty_strategy(f"Strategy selection failed: {exc}"),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Archetype scoring
# ---------------------------------------------------------------------------

def _score_archetype(
    key: str,
    opts: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    metrics: dict[str, Any],
    kpi: dict[str, Any],
) -> tuple[float, list[str]]:
    """Score an archetype based on current metrics. Returns (score, reasons)."""
    score = 0.0
    reasons: list[str] = []

    net_margin = float(metrics.get("net_margin", 0.0))
    net_profit = float(metrics.get("net_profit", 0.0))
    roas = float(kpi.get("roas", 0.0))
    health_score = float(kpi.get("health_score", 0.0))
    conversion_rate = float(kpi.get("conversion_rate", 0.0))

    if key == "maximize_margin":
        if net_margin < 0.10:
            score += 40
            reasons.append(f"Net margin is thin at {net_margin:.1%}")
        if net_margin < 0:
            score += 30
            reasons.append("Business is currently unprofitable")
        if net_margin >= 0.20:
            score -= 10
            reasons.append("Margins already healthy")
        # Count matching optimizations
        preferred = _ARCHETYPES[key]["preferred_actions"]
        matches = sum(1 for o in opts if o.get("action", "") in preferred)
        score += matches * 8
        if matches:
            reasons.append(f"{matches} margin-focused optimizations available")

    elif key == "scale_revenue":
        if roas >= 4.0:
            score += 30
            reasons.append(f"Strong ROAS at {roas:.1f}x supports scaling")
        if net_margin > 0.15:
            score += 20
            reasons.append(f"Healthy margins ({net_margin:.1%}) provide scaling runway")
        if health_score > 0.7:
            score += 15
            reasons.append(f"Overall health score {health_score:.0%} is strong")
        if net_margin < 0.05:
            score -= 20
            reasons.append("Margins too thin for aggressive scaling")
        preferred = _ARCHETYPES[key]["preferred_actions"]
        matches = sum(1 for o in opts if o.get("action", "") in preferred)
        score += matches * 8

    elif key == "reduce_costs":
        total_cost = float(metrics.get("total_cost", 0.0))
        net_revenue = float(metrics.get("net_revenue", 0.0))
        cost_ratio = total_cost / net_revenue if net_revenue > 0 else 1.0
        if cost_ratio > 0.85:
            score += 35
            reasons.append(f"Cost-to-revenue ratio is {cost_ratio:.1%}")
        if net_profit < 0:
            score += 25
            reasons.append("Currently unprofitable — cost cuts needed")
        preferred = _ARCHETYPES[key]["preferred_actions"]
        matches = sum(1 for o in opts if o.get("action", "") in preferred)
        score += matches * 8
        if matches:
            reasons.append(f"{matches} cost-reduction optimizations available")

    elif key == "balanced_growth":
        # Balanced is the default; moderate score always
        score += 30
        reasons.append("Balanced approach suitable for most situations")
        if 0.05 < net_margin < 0.20:
            score += 15
            reasons.append("Moderate margins favor balanced strategy")
        if 2.0 < roas < 5.0:
            score += 10
            reasons.append("Moderate ROAS supports balanced approach")
        score += len(opts) * 3

    return max(score, 0.0), reasons


def _compute_strategy_risk(
    selected_opts: list[dict[str, Any]],
    risks: list[dict[str, Any]],
) -> str:
    """Compute overall risk level for selected optimizations."""
    if not risks:
        return "medium"

    risk_map = {r["optimization_id"]: r for r in risks if "optimization_id" in r}

    selected_ids = {o["optimization_id"] for o in selected_opts}
    relevant_risks = [
        float(risk_map[oid].get("overall_risk", 0.5))
        for oid in selected_ids
        if oid in risk_map
    ]

    if not relevant_risks:
        return "medium"

    avg_risk = sum(relevant_risks) / len(relevant_risks)
    if avg_risk >= 0.7:
        return "high"
    if avg_risk >= 0.4:
        return "medium"
    return "low"


def _empty_strategy(reason: str) -> dict[str, Any]:
    """Return an empty strategy placeholder."""
    return {
        "strategy_id": "none",
        "name": "None",
        "description": reason,
        "optimization_ids": [],
        "expected_total_profit_change": 0.0,
        "expected_total_revenue_change": 0.0,
        "risk_level": "unknown",
        "confidence": 0.0,
        "reasoning": [reason],
    }
