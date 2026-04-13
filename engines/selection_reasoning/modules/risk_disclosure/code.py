"""Risk Disclosure — honestly discloses all risks of the selection.

Lists every identified risk with severity rating, a concrete mitigation
plan, and worst-case scenario including potential financial loss. This
module prioritizes transparency — it does not downplay or hide risks.

Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import RISK_TEMPLATES, MITIGATION_LIBRARY, WORST_CASE_FACTORS
from .logic import prioritize_risks, generate_mitigation_plan, calculate_worst_case
from .rules import validate_risk_disclosure


def disclose_risks(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Generate a transparent risk disclosure for the selected product.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): chosen product with risk data
            - engine_results (dict): all upstream engine outputs
            - investment (float): estimated initial investment amount
            - confidence (dict): confidence assessment
            - goal (str): profit|growth|balanced

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product")
        if not selected or not isinstance(selected, dict):
            return _error("selected_product is required")

        engine_results = input_payload.get("engine_results", {})
        investment = input_payload.get("investment", 5000.0)
        confidence = input_payload.get("confidence", {})
        goal = input_payload.get("goal", "balanced")

        # --- Extract risks from product data ---
        raw_risks = _extract_risks(selected, engine_results, confidence)

        # --- Prioritize risks by severity ---
        prioritized = prioritize_risks(raw_risks)

        # --- Generate mitigation plan for each risk ---
        disclosed_risks: list[dict[str, Any]] = []
        for risk in prioritized:
            mitigation = generate_mitigation_plan(risk)
            risk["mitigation"] = mitigation
            disclosed_risks.append(risk)

        # --- Calculate worst-case scenario ---
        worst_case = calculate_worst_case(disclosed_risks, investment)

        # --- Count by severity ---
        severity_counts = _count_severities(disclosed_risks)

        # --- Build risk summary ---
        risk_summary = _build_risk_summary(disclosed_risks, worst_case, investment)

        # --- Validate disclosure ---
        validation = validate_risk_disclosure(disclosed_risks, worst_case)

        return {
            "status": "success",
            "data": {
                "risks": disclosed_risks,
                "worst_case": worst_case,
                "risk_summary": risk_summary,
                "severity_counts": severity_counts,
                "total_risks": len(disclosed_risks),
                "investment_at_risk": investment,
                "validation": validation,
            },
            "meta": {
                "module": "risk_disclosure",
                "risks_identified": len(disclosed_risks),
                "highest_severity": _highest_severity(severity_counts),
                "goal": goal,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Risk disclosure failed: {exc}")


def _extract_risks(
    selected: dict[str, Any],
    engine_results: dict[str, Any],
    confidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract all risk factors from product and engine data."""
    risks: list[dict[str, Any]] = []

    # --- Risk engine data ---
    risk_data = selected.get("risk", {}) or {}
    composite = risk_data.get("composite_risk", 0)
    risk_level = risk_data.get("risk_level", "unknown")

    if composite > 0:
        severity = _risk_score_to_severity(composite)
        risks.append({
            "id": "composite_risk",
            "name": "Overall Risk Profile",
            "description": f"Composite risk score is {composite:.0f}/100 ({risk_level})",
            "severity": severity,
            "source": "Product Risk Engine",
            "score": composite,
        })

    # --- Competition risk ---
    comp = selected.get("competition", {}) or {}
    comp_score = comp.get("competition_score", 50)
    landscape = comp.get("competitive_landscape", "")
    if comp_score < 40:
        risks.append({
            "id": "high_competition",
            "name": "High Competition",
            "description": (
                f"Competition score is {comp_score:.0f}/100 ({landscape}). "
                f"Market is crowded and price wars are likely."
            ),
            "severity": "high" if comp_score < 25 else "moderate",
            "source": "Competition Analyzer Engine",
            "score": 100 - comp_score,
        })

    # --- Demand risk ---
    demand = selected.get("demand", {}) or {}
    demand_score = demand.get("demand_score", 50)
    if demand_score < 40:
        risks.append({
            "id": "low_demand",
            "name": "Low Market Demand",
            "description": (
                f"Demand score is {demand_score:.0f}/100. Insufficient market "
                f"pull may result in slow sales and inventory buildup."
            ),
            "severity": "high" if demand_score < 25 else "moderate",
            "source": "Demand Estimator Engine",
            "score": 100 - demand_score,
        })

    # --- Margin risk ---
    profit = selected.get("profitability", {}) or {}
    margin = profit.get("margin", 0)
    if margin < 20:
        risks.append({
            "id": "thin_margins",
            "name": "Thin Profit Margins",
            "description": (
                f"Margin is {margin:.1f}%. After unexpected costs (returns, "
                f"advertising, storage), actual profit may be near zero."
            ),
            "severity": "high" if margin < 10 else "moderate",
            "source": "Profitability Calculator Engine",
            "score": max(0, 100 - margin * 5),
        })

    # --- Confidence risk ---
    conf_level = confidence.get("level", "moderate")
    if conf_level == "low":
        risks.append({
            "id": "low_confidence",
            "name": "Low Data Confidence",
            "description": (
                "Decision confidence is low due to missing or incomplete engine data. "
                "Projections may be unreliable."
            ),
            "severity": "moderate",
            "source": "Selection Decision Engine",
            "score": 60,
        })

    # --- Trend risk ---
    trend = selected.get("trend_discovery", {}) or {}
    trend_score = trend.get("trend_score", 50)
    if trend_score < 30:
        risks.append({
            "id": "declining_trend",
            "name": "Declining or Flat Trend",
            "description": (
                f"Trend score is {trend_score:.0f}/100. The product may be past "
                f"its peak or entering a declining market."
            ),
            "severity": "moderate",
            "source": "Trend Discovery Engine",
            "score": 100 - trend_score,
        })

    # Always include at least a baseline risk entry
    if not risks:
        risks.append({
            "id": "general_market_risk",
            "name": "General Market Risk",
            "description": (
                "All product launches carry inherent market risk including "
                "demand variability, pricing pressure, and supply chain disruptions."
            ),
            "severity": "low",
            "source": "Selection Reasoning Engine",
            "score": 20,
        })

    return risks


def _risk_score_to_severity(score: float) -> str:
    """Convert a numeric risk score to a severity label."""
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "moderate"
    return "low"


def _count_severities(risks: list[dict[str, Any]]) -> dict[str, int]:
    """Count risks by severity level."""
    counts: dict[str, int] = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
    for risk in risks:
        severity = risk.get("severity", "low")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _highest_severity(counts: dict[str, int]) -> str:
    """Return the highest severity level that has at least one risk."""
    for level in ("critical", "high", "moderate", "low"):
        if counts.get(level, 0) > 0:
            return level
    return "none"


def _build_risk_summary(
    risks: list[dict[str, Any]],
    worst_case: dict[str, Any],
    investment: float,
) -> str:
    """Build a human-readable risk summary."""
    total = len(risks)
    loss = worst_case.get("maximum_loss", 0)
    loss_pct = worst_case.get("loss_percentage", 0)

    high_critical = sum(
        1 for r in risks if r.get("severity") in ("high", "critical")
    )

    if high_critical == 0:
        return (
            f"{total} risk(s) identified, all at moderate or low severity. "
            f"Worst-case loss: ${loss:,.0f} ({loss_pct:.0f}% of ${investment:,.0f} investment)."
        )

    return (
        f"{total} risk(s) identified, including {high_critical} high/critical. "
        f"Worst-case loss: ${loss:,.0f} ({loss_pct:.0f}% of ${investment:,.0f} investment). "
        f"Mitigation plans are provided for each risk."
    )


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "risk_disclosure"},
        "error": message,
    }
