"""Learning Loop — pattern analyzer.

Finds recurring patterns across historical results: what works, what fails,
when, and why. Detects correlations between decisions and outcomes.

Model note: Would use Mistral for deeper analytical pattern recognition.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def analyze_patterns(
    task: str,
    decision: str,
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
    evaluation: dict[str, Any],
    errors: list[dict[str, Any]],
    past_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find recurring patterns across current and historical results.

    Args:
        task: The current task type.
        decision: The current decision.
        raw_metrics: Raw collected metrics.
        derived_metrics: Computed derived metrics.
        evaluation: Evaluation result from the evaluator.
        errors: Detected errors from error detector.
        past_records: Historical learning records.

    Returns:
        Structured dict with detected patterns.
    """
    try:
        patterns: list[dict[str, Any]] = []

        patterns.extend(_detect_performance_trends(
            task, evaluation, past_records,
        ))
        patterns.extend(_detect_decision_outcome_correlations(
            decision, evaluation, past_records,
        ))
        patterns.extend(_detect_recurring_errors(
            errors, past_records,
        ))
        patterns.extend(_detect_metric_correlations(
            raw_metrics, derived_metrics,
        ))
        patterns.extend(_detect_task_patterns(
            task, past_records,
        ))

        patterns.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)

        return {
            "status": "success",
            "patterns": patterns,
            "pattern_count": len(patterns),
            "model_note": "Mistral would provide deeper causal pattern analysis",
        }
    except Exception as exc:
        return {
            "status": "error",
            "patterns": [],
            "pattern_count": 0,
            "error": str(exc),
        }


def _detect_performance_trends(
    task: str,
    evaluation: dict[str, Any],
    past_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect whether performance is trending up, down, or stable."""
    patterns: list[dict[str, Any]] = []

    task_records = [
        r for r in past_records
        if task.lower() in r.get("task", "").lower()
    ]
    if len(task_records) < 2:
        return patterns

    scores = [r.get("score", 0.0) for r in task_records]
    current_score = evaluation.get("score", 0.0)
    all_scores = scores + [current_score]

    if len(all_scores) >= 3:
        recent = all_scores[-3:]
        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        avg_diff = sum(diffs) / len(diffs)

        if avg_diff > 0.05:
            patterns.append({
                "type": "improving_trend",
                "detail": f"Performance for '{task}' has been improving over the last "
                          f"{len(recent)} runs (avg change: +{round(avg_diff * 100, 1)}%)",
                "frequency": len(recent),
                "confidence": min(0.9, 0.5 + abs(avg_diff) * 2),
                "supporting_records": len(task_records),
            })
        elif avg_diff < -0.05:
            patterns.append({
                "type": "declining_trend",
                "detail": f"Performance for '{task}' has been declining over the last "
                          f"{len(recent)} runs (avg change: {round(avg_diff * 100, 1)}%)",
                "frequency": len(recent),
                "confidence": min(0.9, 0.5 + abs(avg_diff) * 2),
                "supporting_records": len(task_records),
            })
        else:
            patterns.append({
                "type": "stable_performance",
                "detail": f"Performance for '{task}' has been stable across "
                          f"{len(recent)} recent runs (score range: "
                          f"{round(min(recent), 2)}-{round(max(recent), 2)})",
                "frequency": len(recent),
                "confidence": 0.6,
                "supporting_records": len(task_records),
            })

    return patterns


def _detect_decision_outcome_correlations(
    decision: str,
    evaluation: dict[str, Any],
    past_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect correlations between decision types and outcomes."""
    patterns: list[dict[str, Any]] = []
    if not past_records:
        return patterns

    decision_keywords = set(decision.lower().replace("_", " ").split())

    matching: list[dict[str, Any]] = []
    non_matching: list[dict[str, Any]] = []

    for record in past_records:
        record_keywords = set(record.get("decision", "").lower().replace("_", " ").split())
        overlap = decision_keywords & record_keywords
        if len(overlap) >= max(1, len(decision_keywords) // 2):
            matching.append(record)
        else:
            non_matching.append(record)

    if len(matching) >= 2:
        match_scores = [r.get("score", 0.0) for r in matching]
        avg_match = sum(match_scores) / len(match_scores)

        perf_labels = [r.get("performance", "unknown") for r in matching]
        good_count = sum(1 for p in perf_labels if p in ("above_average",))
        bad_count = sum(1 for p in perf_labels if p in ("below_average", "poor"))

        if good_count > bad_count and avg_match > 0.5:
            patterns.append({
                "type": "decision_success_correlation",
                "detail": f"Similar decisions to '{decision}' have historically performed well "
                          f"(avg score: {round(avg_match, 2)}, {good_count}/{len(matching)} above average)",
                "frequency": len(matching),
                "confidence": min(0.85, 0.4 + (good_count / len(matching)) * 0.5),
                "supporting_records": len(matching),
            })
        elif bad_count > good_count and avg_match < 0.4:
            patterns.append({
                "type": "decision_failure_correlation",
                "detail": f"Similar decisions to '{decision}' have historically underperformed "
                          f"(avg score: {round(avg_match, 2)}, {bad_count}/{len(matching)} below average)",
                "frequency": len(matching),
                "confidence": min(0.85, 0.4 + (bad_count / len(matching)) * 0.5),
                "supporting_records": len(matching),
            })

    if matching and non_matching:
        match_avg = sum(r.get("score", 0.0) for r in matching) / len(matching)
        non_match_avg = sum(r.get("score", 0.0) for r in non_matching) / len(non_matching)
        diff = match_avg - non_match_avg

        if abs(diff) > 0.15:
            direction = "better" if diff > 0 else "worse"
            patterns.append({
                "type": "decision_comparative_pattern",
                "detail": f"Decisions similar to '{decision}' perform {direction} than dissimilar ones "
                          f"by {round(abs(diff) * 100, 1)}% on average",
                "frequency": len(matching) + len(non_matching),
                "confidence": min(0.8, 0.3 + min(len(matching), 5) * 0.1),
                "supporting_records": len(matching) + len(non_matching),
            })

    return patterns


def _detect_recurring_errors(
    current_errors: list[dict[str, Any]],
    past_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect error types that keep recurring across runs."""
    patterns: list[dict[str, Any]] = []
    if not current_errors or not past_records:
        return patterns

    historical_error_types: dict[str, int] = {}
    for record in past_records:
        for err in record.get("errors", []):
            etype = err.get("type", "")
            if etype:
                historical_error_types[etype] = historical_error_types.get(etype, 0) + 1

    current_types = {e.get("type", "") for e in current_errors}

    for etype in current_types:
        if not etype:
            continue
        hist_count = historical_error_types.get(etype, 0)
        if hist_count >= 2:
            total_occurrences = hist_count + 1
            frequency_ratio = total_occurrences / (len(past_records) + 1)
            patterns.append({
                "type": "recurring_error",
                "detail": f"Error '{etype}' has occurred {total_occurrences} times across "
                          f"{len(past_records) + 1} runs ({round(frequency_ratio * 100, 1)}% occurrence rate)",
                "frequency": total_occurrences,
                "confidence": min(0.9, 0.4 + frequency_ratio * 0.5),
                "supporting_records": hist_count,
            })

    return patterns


def _detect_metric_correlations(
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
) -> list[dict[str, Any]]:
    """Detect notable metric relationships in the current result."""
    patterns: list[dict[str, Any]] = []
    all_metrics = {**raw_metrics, **derived_metrics}

    ctr = all_metrics.get("ctr", 0.0)
    conv = all_metrics.get("conversion_rate", 0.0)
    views = all_metrics.get("views", 0)
    roas = all_metrics.get("roas", 0.0)
    profit_margin = all_metrics.get("profit_margin", 0.0)
    bounce_rate = all_metrics.get("bounce_rate", 0.0)

    if ctr > 3.0 and conv > 5.0:
        patterns.append({
            "type": "high_funnel_efficiency",
            "detail": f"Both CTR ({round(ctr, 1)}%) and conversion ({round(conv, 1)}%) are strong, "
                      f"indicating good audience-offer alignment",
            "frequency": 1,
            "confidence": 0.75,
            "supporting_records": 0,
        })
    elif ctr > 3.0 and conv < 1.5:
        patterns.append({
            "type": "funnel_disconnect",
            "detail": f"High CTR ({round(ctr, 1)}%) but low conversion ({round(conv, 1)}%) suggests "
                      f"ad creative attracts clicks but landing page or offer does not convert",
            "frequency": 1,
            "confidence": 0.8,
            "supporting_records": 0,
        })

    if views > 500 and ctr < 0.5:
        patterns.append({
            "type": "low_attention_capture",
            "detail": f"With {int(views)} views but only {round(ctr, 2)}% CTR, "
                      f"the creative or targeting likely needs improvement",
            "frequency": 1,
            "confidence": 0.7,
            "supporting_records": 0,
        })

    if roas > 3.0 and profit_margin > 30.0:
        patterns.append({
            "type": "high_profitability_signal",
            "detail": f"Strong ROAS ({round(roas, 1)}x) combined with healthy margin "
                      f"({round(profit_margin, 1)}%) indicates a highly profitable campaign",
            "frequency": 1,
            "confidence": 0.8,
            "supporting_records": 0,
        })

    if bounce_rate > 60.0 and conv < 2.0:
        patterns.append({
            "type": "landing_page_issue",
            "detail": f"High bounce rate ({round(bounce_rate, 1)}%) paired with low conversion "
                      f"({round(conv, 1)}%) points to a landing page experience problem",
            "frequency": 1,
            "confidence": 0.75,
            "supporting_records": 0,
        })

    return patterns


def _detect_task_patterns(
    task: str,
    past_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect patterns specific to this task type across history."""
    patterns: list[dict[str, Any]] = []
    if not past_records:
        return patterns

    task_records = [
        r for r in past_records
        if task.lower() in r.get("task", "").lower()
    ]
    if len(task_records) < 3:
        return patterns

    scores = [r.get("score", 0.0) for r in task_records]
    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std > 0.2:
        patterns.append({
            "type": "high_variance_task",
            "detail": f"Task '{task}' shows high performance variance (std: {round(std, 3)}) "
                      f"across {len(task_records)} runs, suggesting inconsistent execution or external factors",
            "frequency": len(task_records),
            "confidence": min(0.8, 0.4 + std),
            "supporting_records": len(task_records),
        })
    elif std < 0.05 and len(task_records) >= 5:
        patterns.append({
            "type": "consistent_task",
            "detail": f"Task '{task}' shows very consistent results (std: {round(std, 3)}) "
                      f"across {len(task_records)} runs at avg score {round(mean_score, 2)}",
            "frequency": len(task_records),
            "confidence": 0.8,
            "supporting_records": len(task_records),
        })

    performances = [r.get("performance", "unknown") for r in task_records]
    perf_counts: dict[str, int] = {}
    for p in performances:
        perf_counts[p] = perf_counts.get(p, 0) + 1

    dominant = max(perf_counts, key=lambda k: perf_counts[k])
    dominant_ratio = perf_counts[dominant] / len(task_records)

    if dominant_ratio >= 0.6 and dominant in ("below_average", "poor"):
        patterns.append({
            "type": "chronically_underperforming_task",
            "detail": f"Task '{task}' has been '{dominant}' in {perf_counts[dominant]}/{len(task_records)} "
                      f"recent runs ({round(dominant_ratio * 100, 1)}%), indicating a systemic issue",
            "frequency": perf_counts[dominant],
            "confidence": min(0.9, 0.5 + dominant_ratio * 0.4),
            "supporting_records": len(task_records),
        })
    elif dominant_ratio >= 0.6 and dominant == "above_average":
        patterns.append({
            "type": "consistently_strong_task",
            "detail": f"Task '{task}' has been '{dominant}' in {perf_counts[dominant]}/{len(task_records)} "
                      f"recent runs, indicating a reliable strategy",
            "frequency": perf_counts[dominant],
            "confidence": min(0.9, 0.5 + dominant_ratio * 0.4),
            "supporting_records": len(task_records),
        })

    return patterns
