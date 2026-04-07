"""Product Agent evaluator — assess quality of product analysis results.

Evaluates:
  - Completeness (did all engines return data?)
  - Product quality (are products well-scored and validated?)
  - Pricing confidence (are pricing recommendations solid?)
  - Risk assessment (are risks identified and mitigated?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate product analysis quality.

    Returns score 0-100 with detailed breakdown.
    """
    # Defensive: caller contract says ``results: dict``
    # but a misbehaving upstream can pass None. Audit
    # pass 36.
    results = results if isinstance(results, dict) else {}
    goal = goal if isinstance(goal, str) else ""
    engine_results = results.get("engine_results") or {}
    if not isinstance(engine_results, dict):
        engine_results = {}
    # ``.get(k, default)`` only returns default when k is
    # MISSING; present-but-None would crash the int math.
    completed = results.get("completed_steps") or 0
    total = results.get("total_steps") or 1
    if not isinstance(completed, (int, float)):
        completed = 0
    if not isinstance(total, (int, float)) or total <= 0:
        total = 1

    scores: dict[str, float] = {}
    issues: list[str] = []
    strengths: list[str] = []

    # 1. Completeness (0-25): Did all engines succeed?
    completeness = round(completed / max(total, 1) * 25)
    scores["completeness"] = completeness
    if completed == total:
        strengths.append(f"All {total} engines completed successfully")
    else:
        issues.append(f"{total - completed}/{total} engines failed")

    # 2. Product quality (0-25): Are products well-scored?
    product_quality = _score_product_quality(engine_results)
    scores["product_quality"] = product_quality
    if product_quality >= 20:
        strengths.append("Strong product scoring and validation results")
    elif product_quality < 10:
        issues.append("Product scoring or validation data is weak")

    # 3. Pricing confidence (0-25): Are pricing recommendations solid?
    pricing_confidence = _score_pricing_confidence(engine_results)
    scores["pricing_confidence"] = pricing_confidence
    if pricing_confidence >= 20:
        strengths.append("Pricing recommendations are well-supported by data")
    elif pricing_confidence < 10:
        issues.append("Pricing data is insufficient or unreliable")

    # 4. Risk assessment (0-25): Are risks identified?
    risk_assessment = _score_risk_assessment(engine_results)
    scores["risk_assessment"] = risk_assessment
    if risk_assessment >= 20:
        strengths.append("Comprehensive risk assessment with mitigation strategies")
    elif risk_assessment < 10:
        issues.append("Risk assessment is incomplete or missing")

    total_score = sum(scores.values())
    total_score = max(0, min(100, round(total_score)))

    quality = "high" if total_score >= 70 else "medium" if total_score >= 40 else "low"

    return {
        "score": total_score,
        "quality": quality,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
        "recommendation": _overall_recommendation(total_score, engine_results),
    }


def _score_product_quality(results: dict[str, Any]) -> float:
    """Score the quality of product scoring and filtering results."""
    score = 0

    # Product filter results
    pf = results.get("product_filter", {})
    if pf.get("status") == "success":
        pf_data = pf.get("data") or {}
        if pf_data.get("filtered_products"):
            score += 5
        if pf_data.get("filter_stats"):
            score += 3

    # Product scoring results
    ps = results.get("product_scoring", {})
    if ps.get("status") == "success":
        ps_data = ps.get("data") or {}
        if ps_data.get("scored_products"):
            score += 5
        if ps_data.get("score_distribution"):
            score += 3

    # Product validation results
    pv = results.get("product_validation", {})
    if pv.get("status") == "success":
        pv_data = pv.get("data") or {}
        if pv_data.get("validated_products"):
            score += 5
        if pv_data.get("validation_summary"):
            score += 4

    return min(25, score)


def _score_pricing_confidence(results: dict[str, Any]) -> float:
    """Score how confident the pricing recommendations are."""
    score = 0

    # Pricing engine results
    pr = results.get("pricing", {})
    if pr.get("status") == "success":
        pr_data = pr.get("data") or {}
        if pr_data.get("price_recommendations"):
            score += 8
        if pr_data.get("competitor_analysis"):
            score += 5
        if pr_data.get("margin_analysis"):
            score += 4

    # Profitability calculator results
    pc = results.get("profitability_calculator", {})
    if pc.get("status") == "success":
        pc_data = pc.get("data") or {}
        if pc_data.get("profitability"):
            score += 5
        if pc_data.get("break_even_analysis"):
            score += 3

    return min(25, score)


def _score_risk_assessment(results: dict[str, Any]) -> float:
    """Score how well risks are identified and assessed."""
    score = 0

    # Product validation risks
    pv = results.get("product_validation", {})
    if pv.get("status") == "success":
        pv_data = pv.get("data") or {}
        if pv_data.get("validated_products"):
            score += 7
        if pv_data.get("risk_flags"):
            score += 5
        if pv_data.get("mitigation_suggestions"):
            score += 5

    # Product risk engine
    pr = results.get("product_risk", {})
    if pr.get("status") == "success":
        pr_data = pr.get("data") or {}
        if pr_data.get("risk_scores"):
            score += 4
        if pr_data.get("risk_categories"):
            score += 4

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    pricing = results.get("pricing", {})
    has_pricing = pricing.get("status") == "success"

    validation = results.get("product_validation", {})
    has_validation = validation.get("status") == "success"

    if score >= 70:
        if has_pricing and has_validation:
            return "Products are well-scored, priced, and validated. Ready for launch."
        return "Product analysis is strong. Complete any missing steps before launch."

    if score >= 40:
        return "Product analysis shows promise but needs refinement in scoring or pricing."

    return "Product analysis is insufficient. Gather more data or broaden product selection."
