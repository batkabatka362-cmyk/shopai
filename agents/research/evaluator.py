"""Research Agent evaluator — assess quality of research results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import (
    ScoreComponent,
    completeness_component,
    evaluate_results_base,
)


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate research quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            completeness_component(),
            ScoreComponent(
                name="data_richness",
                scorer=lambda er, meta: _score_data_richness(er),
                strong_text="Rich data across multiple dimensions",
                weak_text="Thin data — results may be unreliable",
            ),
            ScoreComponent(
                name="signal_agreement",
                scorer=lambda er, meta: _score_signal_agreement(er),
                strong_text="Multiple engines agree on opportunity assessment",
                weak_text="Engines disagree — conflicting signals",
            ),
            ScoreComponent(
                name="actionability",
                scorer=lambda er, meta: _score_actionability(er),
                strong_text="Clear actionable recommendations available",
                weak_text="No clear actionable recommendation",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_data_richness(results: dict[str, Any]) -> float:
    """Score how rich/complete the data is."""
    score = 0

    mr = results.get("market_research", {})
    if isinstance(mr, dict) and mr.get("status") == "success":
        mr_data = mr.get("data") or {}
        if mr_data.get("market_size"):
            score += 5
        if mr_data.get("trends"):
            score += 3
        if mr_data.get("seasonality"):
            score += 3
        gaps = mr_data.get("gaps")
        if isinstance(gaps, dict) and (gaps.get("data") or {}).get("total_gaps_found", 0) > 0:
            score += 5
        saturation = mr_data.get("saturation")
        if isinstance(saturation, dict) and saturation.get("data"):
            score += 4

    td = results.get("trend_discovery", {})
    if isinstance(td, dict) and td.get("status") == "success":
        td_data = td.get("data") or {}
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

    mr = results.get("market_research", {})
    if isinstance(mr, dict) and mr.get("status") == "success":
        verdict = (mr.get("data") or {}).get("verdict", {})
        if isinstance(verdict, dict):
            mr_score = verdict.get("score", 50)
            signals.append(mr_score)

    td = results.get("trend_discovery", {})
    if isinstance(td, dict) and td.get("status") == "success":
        td_data = td.get("data") or {}
        if td_data.get("trend_scores"):
            score_data = td_data["trend_scores"]
            if isinstance(score_data, dict):
                signals.append((score_data.get("data") or {}).get("composite_score", 50))

    if len(signals) < 2:
        return 10  # Can't assess agreement with 1 signal

    avg = sum(signals) / len(signals)
    variance = sum((s - avg) ** 2 for s in signals) / len(signals)
    max_variance = 2500  # Max possible variance (0 vs 100)

    agreement_pct = max(0, 1 - variance / max_variance)
    return round(agreement_pct * 25)


def _score_actionability(results: dict[str, Any]) -> float:
    """Score how actionable the results are."""
    score = 0

    mr = results.get("market_research", {})
    if isinstance(mr, dict) and mr.get("status") == "success":
        verdict = (mr.get("data") or {}).get("verdict", {})
        if isinstance(verdict, dict) and verdict.get("verdict"):
            score += 10
        if (mr.get("data") or {}).get("summary"):
            score += 5

    td = results.get("trend_discovery", {})
    if isinstance(td, dict) and td.get("status") == "success":
        td_data = td.get("data") or {}
        search_trends = td_data.get("search_trends")
        if isinstance(search_trends, dict) and (search_trends.get("data") or {}).get("top_opportunities"):
            score += 7
        trend_scores = td_data.get("trend_scores")
        if isinstance(trend_scores, dict) and (trend_scores.get("data") or {}).get("action"):
            score += 3

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    mr = results.get("market_research", {})
    mr_verdict = ""
    if isinstance(mr, dict) and mr.get("status") == "success":
        verdict = (mr.get("data") or {}).get("verdict", {})
        if isinstance(verdict, dict):
            mr_verdict = verdict.get("verdict", "")

    if score >= 70:
        if mr_verdict in ("strong_enter", "enter_with_caution"):
            return "Research strongly supports proceeding. Market opportunity confirmed by multiple signals."
        return "Research quality is high. Review specific recommendations before proceeding."

    if score >= 40:
        return "Research shows mixed signals. Gather additional data before making major investment."

    return "Research quality is low. Recommend additional data collection before making decisions."
