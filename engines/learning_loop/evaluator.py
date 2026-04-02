"""Learning Loop — evaluator.

Evaluates execution performance against benchmarks and past performance.
Classifies results as above_average, average, below_average, or poor.

Model note: Would use Mistral for nuanced evaluation reasoning.
"""
from __future__ import annotations

import copy
from typing import Any


_BENCHMARKS: dict[str, dict[str, float]] = {
    "ad_campaign": {
        "ctr": 2.0,
        "conversion_rate": 3.5,
        "roas": 2.5,
        "bounce_rate": 45.0,
        "engagement_rate": 4.0,
        "cpa": 25.0,
        "profit_margin": 20.0,
    },
    "email_marketing": {
        "ctr": 3.5,
        "conversion_rate": 4.0,
        "roas": 4.0,
        "bounce_rate": 30.0,
        "engagement_rate": 6.0,
        "cpa": 15.0,
        "profit_margin": 30.0,
    },
    "social_media": {
        "ctr": 1.5,
        "conversion_rate": 2.0,
        "roas": 1.8,
        "bounce_rate": 50.0,
        "engagement_rate": 5.0,
        "cpa": 30.0,
        "profit_margin": 15.0,
    },
    "default": {
        "ctr": 2.0,
        "conversion_rate": 3.0,
        "roas": 2.0,
        "bounce_rate": 40.0,
        "engagement_rate": 4.0,
        "cpa": 20.0,
        "profit_margin": 20.0,
    },
}


def evaluate_performance(
    task: str,
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
    summary: dict[str, Any],
    past_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate performance by comparing metrics against benchmarks and history.

    Args:
        task: The task type for benchmark selection.
        raw_metrics: Raw collected metrics.
        derived_metrics: Computed derived metrics.
        summary: Summary scores from result collector.
        past_records: Historical learning records for comparison.

    Returns:
        Structured dict with performance label, score, and deviations.
    """
    try:
        benchmarks = _select_benchmarks(task)
        past_averages = _compute_past_averages(past_records)

        deviations: dict[str, float] = {}
        deviation_scores: list[float] = []

        for metric, benchmark_val in benchmarks.items():
            if benchmark_val == 0.0:
                continue
            actual = derived_metrics.get(metric, 0.0)

            if metric in ("bounce_rate", "cpa"):
                deviation = (benchmark_val - actual) / benchmark_val
            else:
                deviation = (actual - benchmark_val) / benchmark_val

            deviations[metric] = round(deviation, 4)
            deviation_scores.append(deviation)

        benchmark_score = _compute_benchmark_score(deviation_scores)

        history_score = 0.5
        history_deviations: dict[str, float] = {}
        if past_averages:
            hist_devs: list[float] = []
            for metric, past_val in past_averages.items():
                if past_val == 0.0:
                    continue
                actual = derived_metrics.get(metric, raw_metrics.get(metric, 0.0))
                if metric in ("bounce_rate", "cpa"):
                    dev = (past_val - actual) / past_val
                else:
                    dev = (actual - past_val) / past_val
                history_deviations[metric] = round(dev, 4)
                hist_devs.append(dev)
            if hist_devs:
                history_score = _compute_benchmark_score(hist_devs)

        overall_score_component = summary.get("overall_score", 0.0)
        combined_score = round(
            benchmark_score * 0.4 + history_score * 0.3 + overall_score_component * 0.3,
            4,
        )

        performance = _classify_performance(combined_score)

        return {
            "status": "success",
            "performance": performance,
            "score": combined_score,
            "benchmark_score": round(benchmark_score, 4),
            "history_score": round(history_score, 4),
            "metrics": copy.deepcopy(derived_metrics),
            "benchmarks": benchmarks,
            "deviations": deviations,
            "history_deviations": history_deviations,
            "model_note": "Mistral would provide nuanced contextual evaluation",
        }
    except Exception as exc:
        return {
            "status": "error",
            "performance": "unknown",
            "score": 0.0,
            "benchmark_score": 0.0,
            "history_score": 0.0,
            "metrics": {},
            "benchmarks": {},
            "deviations": {},
            "history_deviations": {},
            "model_note": "",
            "error": str(exc),
        }


def _select_benchmarks(task: str) -> dict[str, float]:
    """Select benchmark set based on task type keywords."""
    task_lower = task.lower()
    for key in _BENCHMARKS:
        if key != "default" and key.replace("_", " ") in task_lower.replace("_", " "):
            return copy.deepcopy(_BENCHMARKS[key])
    if "ad" in task_lower or "campaign" in task_lower:
        return copy.deepcopy(_BENCHMARKS["ad_campaign"])
    if "email" in task_lower:
        return copy.deepcopy(_BENCHMARKS["email_marketing"])
    if "social" in task_lower:
        return copy.deepcopy(_BENCHMARKS["social_media"])
    return copy.deepcopy(_BENCHMARKS["default"])


def _compute_past_averages(records: list[dict[str, Any]]) -> dict[str, float]:
    """Compute average metric values from past records."""
    if not records:
        return {}

    accumulators: dict[str, list[float]] = {}
    for record in records:
        result = record.get("result", {})
        derived = record.get("derived_metrics", {})
        source = derived if derived else result
        for key, val in source.items():
            if isinstance(val, (int, float)):
                if key not in accumulators:
                    accumulators[key] = []
                accumulators[key].append(float(val))

    return {
        k: round(sum(v) / len(v), 4)
        for k, v in accumulators.items()
        if v
    }


def _compute_benchmark_score(deviations: list[float]) -> float:
    """Convert a list of deviations into a 0-1 score."""
    if not deviations:
        return 0.5
    clamped = [max(-1.0, min(1.0, d)) for d in deviations]
    avg = sum(clamped) / len(clamped)
    return round(max(0.0, min(1.0, 0.5 + avg * 0.5)), 4)


def _classify_performance(score: float) -> str:
    """Classify a 0-1 score into a performance label."""
    if score >= 0.7:
        return "above_average"
    if score >= 0.45:
        return "average"
    if score >= 0.25:
        return "below_average"
    return "poor"
