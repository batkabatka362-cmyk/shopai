"""Simulation Lab — strategy comparator.

Compares different strategies side by side using multi-objective scoring.
Produces a ranked list with per-objective scores, pros, and cons.

Model note: Would use Qwen for structured comparison output.
"""
from __future__ import annotations

import copy
from typing import Any


# Default objective weights (normalized to 1.0 at scoring time)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "revenue": 0.25,
    "profit": 0.30,
    "risk": 0.20,
    "roi": 0.15,
    "growth": 0.10,
}


def compare_strategies(
    predictions: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    risk_assessments: list[dict[str, Any]],
    performance_estimates: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    objectives: list[str] | None = None,
) -> dict[str, Any]:
    """Compare all strategies side by side and rank them.

    Args:
        predictions: OutcomePrediction per scenario.
        analyses: AnalysisResult per scenario.
        risk_assessments: RiskAssessment per scenario.
        performance_estimates: PerformanceEstimate per scenario.
        scenarios: Original Scenario dicts.
        objectives: Which objectives to optimize (defaults to all).

    Returns:
        Structured dict with ranked ComparisonEntry list.
    """
    try:
        preds = {p["scenario_id"]: p for p in copy.deepcopy(predictions)}
        anals = {a["scenario_id"]: a for a in copy.deepcopy(analyses)}
        risks = {r["scenario_id"]: r for r in copy.deepcopy(risk_assessments)}
        perfs = {e["scenario_id"]: e for e in copy.deepcopy(performance_estimates)}
        scen_map = {s["scenario_id"]: s for s in copy.deepcopy(scenarios)}

        active_objectives = objectives if objectives else list(_DEFAULT_WEIGHTS.keys())

        # Collect raw metric vectors for normalization
        all_sids = list(preds.keys())
        raw_metrics = _collect_raw_metrics(all_sids, preds, risks, perfs)

        # Normalize to 0-1 scale per metric
        normalized = _normalize_metrics(raw_metrics)

        # Score each scenario
        entries: list[dict[str, Any]] = []
        for sid in all_sids:
            norm = normalized.get(sid, {})
            scenario = scen_map.get(sid, {})
            analysis = anals.get(sid, {})
            risk = risks.get(sid, {})
            perf = perfs.get(sid, {})

            scores = _compute_scores(norm, active_objectives)
            total = _weighted_total(scores, active_objectives)

            pros = _derive_pros(analysis, perf, risk)
            cons = _derive_cons(analysis, perf, risk)

            entries.append({
                "scenario_id": sid,
                "label": scenario.get("label", sid),
                "rank": 0,  # filled after sort
                "scores": scores,
                "total_score": round(total, 4),
                "pros": pros,
                "cons": cons,
            })

        # Sort by total_score descending, assign ranks
        entries.sort(key=lambda e: e["total_score"], reverse=True)
        for i, entry in enumerate(entries):
            entry["rank"] = i + 1

        return {
            "status": "success",
            "comparison": entries,
            "count": len(entries),
            "objectives_used": active_objectives,
        }
    except Exception as exc:
        return {
            "status": "error",
            "comparison": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_raw_metrics(
    sids: list[str],
    preds: dict[str, dict],
    risks: dict[str, dict],
    perfs: dict[str, dict],
) -> dict[str, dict[str, float]]:
    """Collect raw numeric metrics per scenario."""
    raw: dict[str, dict[str, float]] = {}
    for sid in sids:
        pred = preds.get(sid, {})
        risk = risks.get(sid, {})
        perf = perfs.get(sid, {})
        raw[sid] = {
            "revenue": float(pred.get("predicted_revenue", 0.0)),
            "profit": float(pred.get("predicted_profit", 0.0)),
            "risk": 1.0 - float(risk.get("overall_risk", 0.5)),  # invert: lower risk = higher score
            "roi": float(pred.get("predicted_roi", 0.0)),
            "growth": float(perf.get("growth_potential", 0.5)),
        }
    return raw


def _normalize_metrics(
    raw: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Min-max normalize each metric across all scenarios."""
    if not raw:
        return {}

    metrics = list(next(iter(raw.values())).keys())
    normalized: dict[str, dict[str, float]] = {sid: {} for sid in raw}

    for metric in metrics:
        values = [raw[sid][metric] for sid in raw]
        lo = min(values)
        hi = max(values)
        span = hi - lo if hi != lo else 1.0
        for sid in raw:
            normalized[sid][metric] = round((raw[sid][metric] - lo) / span, 4)

    return normalized


def _compute_scores(
    normalized: dict[str, float],
    objectives: list[str],
) -> dict[str, float]:
    """Extract scores for active objectives."""
    return {
        obj: round(normalized.get(obj, 0.0), 4)
        for obj in objectives
    }


def _weighted_total(
    scores: dict[str, float],
    objectives: list[str],
) -> float:
    """Compute weighted total score."""
    total = 0.0
    weight_sum = 0.0
    for obj in objectives:
        w = _DEFAULT_WEIGHTS.get(obj, 0.1)
        total += scores.get(obj, 0.0) * w
        weight_sum += w
    return total / weight_sum if weight_sum > 0 else 0.0


def _derive_pros(
    analysis: dict[str, Any],
    perf: dict[str, Any],
    risk: dict[str, Any],
) -> list[str]:
    """Derive pros from analysis and performance data."""
    pros: list[str] = []
    strengths = analysis.get("strengths", [])
    for s in strengths[:2]:
        if "no notable" not in s.lower():
            pros.append(s)

    growth = float(perf.get("growth_potential", 0.0))
    if growth > 0.7:
        pros.append(f"High growth potential ({growth:.0%})")

    risk_cat = risk.get("risk_category", "medium")
    if risk_cat == "low":
        pros.append("Low risk category")

    if not pros:
        pros.append("Meets baseline expectations")

    return pros[:4]


def _derive_cons(
    analysis: dict[str, Any],
    perf: dict[str, Any],
    risk: dict[str, Any],
) -> list[str]:
    """Derive cons from analysis and risk data."""
    cons: list[str] = []
    weaknesses = analysis.get("weaknesses", [])
    for w in weaknesses[:2]:
        if "no notable" not in w.lower():
            cons.append(w)

    risk_cat = risk.get("risk_category", "medium")
    if risk_cat in ("high", "critical"):
        cons.append(f"Risk category: {risk_cat}")

    scalability = float(perf.get("scalability_score", 0.5))
    if scalability < 0.35:
        cons.append(f"Low scalability ({scalability:.0%})")

    if not cons:
        cons.append("No significant drawbacks identified")

    return cons[:4]
