"""Time Intelligence — time estimator.

Estimates execution time for each task based on type, complexity,
and historical averages.

Model note: Would use Qwen for structured time estimation.
"""
from __future__ import annotations

import copy
from typing import Any

_BASE_DURATIONS: dict[str, float] = {
    "launch_ad": 120.0,
    "update_inventory": 30.0,
    "send_email": 15.0,
    "process_order": 5.0,
    "generate_report": 180.0,
    "sync_catalog": 90.0,
    "notify_customer": 10.0,
    "run_campaign": 300.0,
    "restock_alert": 8.0,
    "price_update": 20.0,
    "backup_data": 600.0,
    "analyze_trends": 240.0,
}

_CLASSIFICATION_MULTIPLIER: dict[str, float] = {
    "realtime": 0.5,
    "triggered": 0.8,
    "scheduled": 1.0,
    "batch": 1.2,
}

_URGENCY_MULTIPLIER: dict[str, float] = {
    "immediate": 0.7,
    "urgent": 0.85,
    "normal": 1.0,
    "deferred": 1.1,
}

_COMPLEXITY_THRESHOLDS: list[tuple[float, str]] = [
    (30.0, "trivial"),
    (60.0, "simple"),
    (180.0, "moderate"),
    (600.0, "complex"),
]


def estimate_times(
    classified_tasks: list[dict[str, Any]],
    priority_results: list[dict[str, Any]],
    past_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate execution time for each task.

    Args:
        classified_tasks: Tasks from the classifier.
        priority_results: Priority scores from the analyzer.
        past_records: Historical execution records for calibration.

    Returns:
        Structured dict with time estimates per task.
    """
    try:
        classified_tasks = copy.deepcopy(classified_tasks)
        priority_map = {p["task_id"]: p for p in priority_results}
        historical_avg = _build_historical_averages(past_records)

        estimates = []
        for task in classified_tasks:
            task_id = task["task_id"]
            task_type = task.get("original_type", "unknown")
            classification = task.get("classification", "batch")
            urgency = task.get("urgency", "normal")

            base = _BASE_DURATIONS.get(task_type, 60.0)

            if task_type in historical_avg:
                base = (base + historical_avg[task_type]) / 2.0

            class_mult = _CLASSIFICATION_MULTIPLIER.get(classification, 1.0)
            urgency_mult = _URGENCY_MULTIPLIER.get(urgency, 1.0)

            dep_count = len(task.get("dependencies", []))
            dep_overhead = dep_count * 2.0

            estimated = (base * class_mult * urgency_mult) + dep_overhead
            estimated = max(1.0, round(estimated, 2))

            complexity = "complex"
            for threshold, label in _COMPLEXITY_THRESHOLDS:
                if estimated <= threshold:
                    complexity = label
                    break

            priority_data = priority_map.get(task_id, {})
            priority_score = priority_data.get("priority_score", 0.5)
            confidence = min(0.95, 0.6 + (priority_score * 0.2))
            if task_type in historical_avg:
                confidence = min(0.98, confidence + 0.1)

            estimates.append({
                "task_id": task_id,
                "estimated_seconds": estimated,
                "complexity": complexity,
                "confidence": round(confidence, 4),
            })

        total = sum(e["estimated_seconds"] for e in estimates)

        return {
            "status": "success",
            "estimates": estimates,
            "total_estimated_seconds": round(total, 2),
            "count": len(estimates),
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimates": [],
            "total_estimated_seconds": 0.0,
            "count": 0,
            "error": str(exc),
        }


def _build_historical_averages(
    past_records: list[dict[str, Any]],
) -> dict[str, float]:
    """Build average durations per task type from historical records."""
    if not past_records:
        return {}

    accum: dict[str, list[float]] = {}
    for record in past_records:
        executions = record.get("executions", [])
        for exe in executions:
            ttype = exe.get("task_type", "")
            duration = exe.get("duration_seconds", 0.0)
            if ttype and duration > 0:
                accum.setdefault(ttype, []).append(duration)

    return {
        ttype: round(sum(durations) / len(durations), 2)
        for ttype, durations in accum.items()
        if durations
    }
