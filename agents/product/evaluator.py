"""Product Agent evaluator — assess quality of product analysis results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
Only the domain-specific scorers and recommendation text live
here; defensive coercion, total-score clamping, quality banding,
and the return envelope come from the shared base.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import (
    ScoreComponent,
    completeness_component,
    evaluate_results_base,
)


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate product analysis quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            completeness_component(),
            ScoreComponent(
                name="product_quality",
                scorer=lambda er, meta: _score_product_quality(er),
                strong_text="Strong product scoring and validation results",
                weak_text="Product scoring or validation data is weak",
            ),
            ScoreComponent(
                name="pricing_confidence",
                scorer=lambda er, meta: _score_pricing_confidence(er),
                strong_text="Pricing recommendations are well-supported by data",
                weak_text="Pricing data is insufficient or unreliable",
            ),
            ScoreComponent(
                name="risk_assessment",
                scorer=lambda er, meta: _score_risk_assessment(er),
                strong_text="Comprehensive risk assessment with mitigation strategies",
                weak_text="Risk assessment is incomplete or missing",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_product_quality(results: dict[str, Any]) -> float:
    """Score the quality of product scoring and filtering results."""
    score = 0

    pf = results.get("product_filter", {})
    if isinstance(pf, dict) and pf.get("status") == "success":
        pf_data = pf.get("data") or {}
        if pf_data.get("filtered_products"):
            score += 5
        if pf_data.get("filter_stats"):
            score += 3

    ps = results.get("product_scoring", {})
    if isinstance(ps, dict) and ps.get("status") == "success":
        ps_data = ps.get("data") or {}
        if ps_data.get("scored_products"):
            score += 5
        if ps_data.get("score_distribution"):
            score += 3

    pv = results.get("product_validation", {})
    if isinstance(pv, dict) and pv.get("status") == "success":
        pv_data = pv.get("data") or {}
        if pv_data.get("validated_products"):
            score += 5
        if pv_data.get("validation_summary"):
            score += 4

    return min(25, score)


def _score_pricing_confidence(results: dict[str, Any]) -> float:
    """Score how confident the pricing recommendations are."""
    score = 0

    pr = results.get("pricing", {})
    if isinstance(pr, dict) and pr.get("status") == "success":
        pr_data = pr.get("data") or {}
        if pr_data.get("price_recommendations"):
            score += 8
        if pr_data.get("competitor_analysis"):
            score += 5
        if pr_data.get("margin_analysis"):
            score += 4

    pc = results.get("profitability_calculator", {})
    if isinstance(pc, dict) and pc.get("status") == "success":
        pc_data = pc.get("data") or {}
        if pc_data.get("profitability"):
            score += 5
        if pc_data.get("break_even_analysis"):
            score += 3

    return min(25, score)


def _score_risk_assessment(results: dict[str, Any]) -> float:
    """Score how well risks are identified and assessed."""
    score = 0

    pv = results.get("product_validation", {})
    if isinstance(pv, dict) and pv.get("status") == "success":
        pv_data = pv.get("data") or {}
        if pv_data.get("validated_products"):
            score += 7
        if pv_data.get("risk_flags"):
            score += 5
        if pv_data.get("mitigation_suggestions"):
            score += 5

    pr = results.get("product_risk", {})
    if isinstance(pr, dict) and pr.get("status") == "success":
        pr_data = pr.get("data") or {}
        if pr_data.get("risk_scores"):
            score += 4
        if pr_data.get("risk_categories"):
            score += 4

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    pricing = results.get("pricing", {})
    has_pricing = isinstance(pricing, dict) and pricing.get("status") == "success"

    validation = results.get("product_validation", {})
    has_validation = isinstance(validation, dict) and validation.get("status") == "success"

    if score >= 70:
        if has_pricing and has_validation:
            return "Products are well-scored, priced, and validated. Ready for launch."
        return "Product analysis is strong. Complete any missing steps before launch."

    if score >= 40:
        return "Product analysis shows promise but needs refinement in scoring or pricing."

    return "Product analysis is insufficient. Gather more data or broaden product selection."
