"""Research Agent evaluator — assess quality of research results.

Evaluates:
  - Data completeness (did all engines return data?)
  - Signal agreement (do engines agree on opportunity?)
  - Confidence level (how confident are the results?)
  - Actionability (can we make decisions from this?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate research quality.

    Returns score 0-100 with detailed breakdown.
    """
    engine_results = results.get("engine_results", {})
    completed = results.get("completed_steps", 0)
    total = results.get("total_steps", 1)

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

    # 2. Data richness (0-25): How much data did we get?
    richness = _score_data_richness(engine_results)
    scores["data_richness"] = richness
    if richness >= 20:
        strengths.append("Rich data across multiple dimensions")
    elif richness < 10:
        issues.append("Thin data — results may be unreliable")

    # 3. Signal agreement (0-25): Do engines agree?
    agreement = _score_signal_agreement(engine_results)
    scores["signal_agreement"] = agreement
    if agreement >= 20:
        strengths.append("Multiple engines agree on opportunity assessment")
    elif agreement < 10:
        issues.append("Engines disagree — conflicting signals")

    # 4. Actionability (0-25): Can we make decisions?
    actionability = _score_actionability(engine_results)
    scores["actionability"] = actionability
    if actionability >= 20:
        strengths.append("Clear actionable recommendations available")
    elif actionability < 10:
        issues.append("No clear actionable recommendation")

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


def _score_data_richness(results: dict[str, Any]) -> float:
    """Score how rich/complete the data is."""
    score = 0

    # Market Research richness
    mr = results.get("market_research", {})
    if mr.get("status") == "success":
        mr_data = mr.get("data", {})
        if mr_data.get("market_size"):
            score += 5
        if mr_data.get("trends"):
            score += 3
        if mr_data.get("seasonality"):
            score += 3
        if mr_data.get("gaps") and mr_data["gaps"].get("data", {}).get("total_gaps_found", 0) > 0:
            score += 5
        if mr_data.get("saturation") and mr_data["saturation"].get("data"):
            score += 4

    # Trend Discovery richness
    td = results.get("trend_discovery", {})
    if td.get("status") == "success":
        td_data = td.get("data", {})
        if td_data.get("search_trends"):
            score += 3
        if td_data.get("social_trends"):
            score += 2
        if td_data.get("marketplace_trends"):
            score += 3
        if td_data.get("emerging_niches"):
            score += 2
        if td_data.get("trend_scores"):
            score += 3

    return min(25, score)


def _score_signal_agreement(results: dict[str, Any]) -> float:
    """Score whether different engines agree on the opportunity."""
    signals = []

    # Market Research verdict
    mr = results.get("market_research", {})
    if mr.get("status") == "success":
        verdict = mr.get("data", {}).get("verdict", {})
        if isinstance(verdict, dict):
            mr_score = verdict.get("score", 50)
            signals.append(mr_score)

    # Trend Discovery verdict
    td = results.get("trend_discovery", {})
    if td.get("status") == "success":
        td_data = td.get("data", {})
        if td_data.get("trend_scores"):
            score_data = td_data["trend_scores"]
            if isinstance(score_data, dict):
                signals.append(score_data.get("data", {}).get("composite_score", 50))

    if len(signals) < 2:
        return 10  # Can't assess agreement with 1 signal

    # Agreement = low variance between signals
    avg = sum(signals) / len(signals)
    variance = sum((s - avg) ** 2 for s in signals) / len(signals)
    max_variance = 2500  # Max possible variance (0 vs 100)

    agreement_pct = max(0, 1 - variance / max_variance)
    return round(agreement_pct * 25)


def _score_actionability(results: dict[str, Any]) -> float:
    """Score how actionable the results are."""
    score = 0

    # Market Research provides clear verdict?
    mr = results.get("market_research", {})
    if mr.get("status") == "success":
        verdict = mr.get("data", {}).get("verdict", {})
        if isinstance(verdict, dict) and verdict.get("verdict"):
            score += 10
        if mr.get("data", {}).get("summary"):
            score += 5

    # Trend Discovery provides clear opportunities?
    td = results.get("trend_discovery", {})
    if td.get("status") == "success":
        td_data = td.get("data", {})
        if td_data.get("search_trends", {}).get("data", {}).get("top_opportunities"):
            score += 7
        if td_data.get("trend_scores", {}).get("data", {}).get("action"):
            score += 3

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    mr = results.get("market_research", {})
    mr_verdict = ""
    if mr.get("status") == "success":
        verdict = mr.get("data", {}).get("verdict", {})
        if isinstance(verdict, dict):
            mr_verdict = verdict.get("verdict", "")

    if score >= 70:
        if mr_verdict in ("strong_enter", "enter_with_caution"):
            return "Research strongly supports proceeding. Market opportunity confirmed by multiple signals."
        return "Research quality is high. Review specific recommendations before proceeding."

    if score >= 40:
        return "Research shows mixed signals. Gather additional data before making major investment."

    return "Research quality is low. Recommend additional data collection before making decisions."
