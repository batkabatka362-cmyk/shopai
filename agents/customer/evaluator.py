"""Customer Agent evaluator — assess quality of customer analysis results.

Evaluates:
  - Segmentation quality (are segments meaningful and actionable?)
  - Churn accuracy (are churn predictions reliable?)
  - Sentiment clarity (is sentiment data clear and usable?)
  - Action specificity (are recommended actions concrete?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate customer analysis quality.

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

    # 1. Segmentation quality (0-25): Are segments meaningful?
    segmentation_quality = _score_segmentation_quality(engine_results)
    scores["segmentation_quality"] = segmentation_quality
    if segmentation_quality >= 20:
        strengths.append("Customer segments are well-defined and actionable")
    elif segmentation_quality < 10:
        issues.append("Segmentation is weak — insufficient customer data")

    # 2. Churn accuracy (0-25): Are churn predictions reliable?
    churn_accuracy = _score_churn_accuracy(engine_results)
    scores["churn_accuracy"] = churn_accuracy
    if churn_accuracy >= 20:
        strengths.append("Churn predictions are reliable with clear risk tiers")
    elif churn_accuracy < 10:
        issues.append("Churn prediction data is insufficient")

    # 3. Sentiment clarity (0-25): Is sentiment data clear?
    sentiment_clarity = _score_sentiment_clarity(engine_results)
    scores["sentiment_clarity"] = sentiment_clarity
    if sentiment_clarity >= 20:
        strengths.append("Sentiment signals are strong and consistent across sources")
    elif sentiment_clarity < 10:
        issues.append("Sentiment data is noisy or unavailable")

    # 4. Action specificity (0-25): Are actions concrete?
    action_specificity = _score_action_specificity(engine_results)
    scores["action_specificity"] = action_specificity
    if action_specificity >= 20:
        strengths.append("Recommended actions are specific and implementable")
    elif action_specificity < 10:
        issues.append("No clear actionable recommendations generated")

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


def _score_segmentation_quality(results: dict[str, Any]) -> float:
    """Score how meaningful customer segments are."""
    score = 0

    seg = results.get("customer_segmentation", {})
    if seg.get("status") == "success":
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
    if churn.get("status") == "success":
        churn_data = churn.get("data") or {}
        if churn_data.get("churn_risks"):
            score += 10
            risks = churn_data["churn_risks"]
            if isinstance(risks, list) and len(risks) > 0:
                # Check if risks have risk levels
                has_levels = any(isinstance(r, dict) and r.get("risk_level") for r in risks)
                if has_levels:
                    score += 8
                # Check if risks have scores
                has_scores = any(isinstance(r, dict) and r.get("score") for r in risks)
                if has_scores:
                    score += 7

    return min(25, score)


def _score_sentiment_clarity(results: dict[str, Any]) -> float:
    """Score sentiment analysis clarity."""
    score = 0

    sent = results.get("sentiment_analysis", {})
    if sent.get("status") == "success":
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

    # Review management actions
    rm = results.get("review_management", {})
    if rm.get("status") == "success":
        rm_data = rm.get("data") or {}
        if rm_data.get("review_actions"):
            score += 10

    # Customer support intelligence
    cs = results.get("customer_support", {})
    if cs.get("status") == "success":
        cs_data = cs.get("data") or {}
        if cs_data.get("support_intelligence"):
            score += 8

    # Audience targeting
    at = results.get("audience_targeting", {})
    if at.get("status") == "success":
        at_data = at.get("data") or {}
        if at_data.get("audiences"):
            score += 7

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    churn = results.get("churn_prediction", {})
    has_high_churn = False
    if churn.get("status") == "success":
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
