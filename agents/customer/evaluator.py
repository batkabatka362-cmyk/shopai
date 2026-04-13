"""Customer Agent evaluator — assess quality of customer analysis results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import ScoreComponent, evaluate_results_base


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate customer analysis quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            ScoreComponent(
                name="segmentation_quality",
                scorer=lambda er, meta: _score_segmentation_quality(er),
                strong_text="Customer segments are well-defined and actionable",
                weak_text="Segmentation is weak — insufficient customer data",
            ),
            ScoreComponent(
                name="churn_accuracy",
                scorer=lambda er, meta: _score_churn_accuracy(er),
                strong_text="Churn predictions are reliable with clear risk tiers",
                weak_text="Churn prediction data is insufficient",
            ),
            ScoreComponent(
                name="sentiment_clarity",
                scorer=lambda er, meta: _score_sentiment_clarity(er),
                strong_text="Sentiment signals are strong and consistent across sources",
                weak_text="Sentiment data is noisy or unavailable",
            ),
            ScoreComponent(
                name="action_specificity",
                scorer=lambda er, meta: _score_action_specificity(er),
                strong_text="Recommended actions are specific and implementable",
                weak_text="No clear actionable recommendations generated",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_segmentation_quality(results: dict[str, Any]) -> float:
    """Score how meaningful customer segments are."""
    score = 0

    seg = results.get("customer_segmentation", {})
    if isinstance(seg, dict) and seg.get("status") == "success":
        seg_data = seg.get("data") or {}
        if seg_data.get("segments"):
            segments = seg_data["segments"]
            score += 8
            if isinstance(segments, list) and len(segments) >= 3:
                score += 5
            if isinstance(segments, list) and len(segments) >= 5:
                score += 3
        if seg_data.get("rfm_analysis"):
            score += 9

    return min(25, score)


def _score_churn_accuracy(results: dict[str, Any]) -> float:
    """Score churn prediction reliability."""
    score = 0

    churn = results.get("churn_prediction", {})
    if isinstance(churn, dict) and churn.get("status") == "success":
        churn_data = churn.get("data") or {}
        if churn_data.get("churn_risks"):
            score += 10
            risks = churn_data["churn_risks"]
            if isinstance(risks, list) and len(risks) > 0:
                has_levels = any(isinstance(r, dict) and r.get("risk_level") for r in risks)
                if has_levels:
                    score += 8
                has_scores = any(isinstance(r, dict) and r.get("score") for r in risks)
                if has_scores:
                    score += 7

    return min(25, score)


def _score_sentiment_clarity(results: dict[str, Any]) -> float:
    """Score sentiment analysis clarity."""
    score = 0

    sent = results.get("sentiment_analysis", {})
    if isinstance(sent, dict) and sent.get("status") == "success":
        sent_data = sent.get("data") or {}
        if sent_data.get("sentiment_scores"):
            score += 12
            sentiment = sent_data["sentiment_scores"]
            if isinstance(sentiment, dict):
                if sentiment.get("positive") is not None:
                    score += 4
                if sentiment.get("negative") is not None:
                    score += 4
                if sentiment.get("themes"):
                    score += 5

    return min(25, score)


def _score_action_specificity(results: dict[str, Any]) -> float:
    """Score how actionable the recommendations are."""
    score = 0

    rm = results.get("review_management", {})
    if isinstance(rm, dict) and rm.get("status") == "success":
        rm_data = rm.get("data") or {}
        if rm_data.get("review_actions"):
            score += 10

    cs = results.get("customer_support", {})
    if isinstance(cs, dict) and cs.get("status") == "success":
        cs_data = cs.get("data") or {}
        if cs_data.get("support_intelligence"):
            score += 8

    at = results.get("audience_targeting", {})
    if isinstance(at, dict) and at.get("status") == "success":
        at_data = at.get("data") or {}
        if at_data.get("audiences"):
            score += 7

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    churn = results.get("churn_prediction", {})
    has_high_churn = False
    if isinstance(churn, dict) and churn.get("status") == "success":
        risks = (churn.get("data") or {}).get("churn_risks", [])
        if isinstance(risks, list):
            has_high_churn = any(
                isinstance(r, dict) and r.get("risk_level") == "high"
                for r in risks
            )

    if score >= 70:
        if has_high_churn:
            return "Customer intelligence is strong. Prioritize retention for high-churn-risk segments."
        return "Customer analysis is comprehensive. Proceed with targeted engagement campaigns."

    if score >= 40:
        return "Customer data shows partial insights. Gather more behavioral data before major campaigns."

    return "Customer analysis is incomplete. Collect more data on orders, reviews, and engagement."
