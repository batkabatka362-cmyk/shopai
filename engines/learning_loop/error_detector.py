"""Learning Loop — error detector.

Detects errors and anomalies in execution results: low conversion,
high bounce rate, missed targets, budget waste, statistical outliers, etc.

Model note: Would use Mistral for contextual anomaly reasoning.
"""
from __future__ import annotations

import copy
import math
from typing import Any


_THRESHOLDS: dict[str, dict[str, Any]] = {
    "low_ctr": {
        "metric": "ctr",
        "direction": "below",
        "critical": 0.5,
        "warning": 1.0,
        "detail_template": "CTR of {actual}% is {severity_word} the {threshold}% threshold",
    },
    "low_conversion": {
        "metric": "conversion_rate",
        "direction": "below",
        "critical": 1.0,
        "warning": 2.0,
        "detail_template": "Conversion rate of {actual}% is {severity_word} the {threshold}% threshold",
    },
    "high_bounce": {
        "metric": "bounce_rate",
        "direction": "above",
        "critical": 75.0,
        "warning": 55.0,
        "detail_template": "Bounce rate of {actual}% exceeds the {threshold}% threshold",
    },
    "high_cpa": {
        "metric": "cpa",
        "direction": "above",
        "critical": 100.0,
        "warning": 50.0,
        "detail_template": "Cost per acquisition of ${actual} exceeds the ${threshold} threshold",
    },
    "negative_roas": {
        "metric": "roas",
        "direction": "below",
        "critical": 0.5,
        "warning": 1.0,
        "detail_template": "ROAS of {actual}x is {severity_word} the {threshold}x threshold",
    },
    "negative_profit": {
        "metric": "profit",
        "direction": "below",
        "critical": -100.0,
        "warning": 0.0,
        "detail_template": "Profit of ${actual} is {severity_word} the ${threshold} threshold",
    },
    "high_return_rate": {
        "metric": "return_rate",
        "direction": "above",
        "critical": 20.0,
        "warning": 10.0,
        "detail_template": "Return rate of {actual}% exceeds the {threshold}% threshold",
    },
    "low_engagement": {
        "metric": "engagement_rate",
        "direction": "below",
        "critical": 0.5,
        "warning": 1.5,
        "detail_template": "Engagement rate of {actual}% is {severity_word} the {threshold}% threshold",
    },
    "zero_sales": {
        "metric": "sales",
        "direction": "below",
        "critical": 0.01,
        "warning": 1.0,
        "detail_template": "Sales count of {actual} is {severity_word} the {threshold} threshold",
    },
}


def detect_errors(
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
    evaluation: dict[str, Any],
    past_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect errors and anomalies in the execution results.

    Args:
        raw_metrics: Raw collected metrics.
        derived_metrics: Computed derived metrics.
        evaluation: Evaluation result from the evaluator.
        past_records: Historical records for statistical anomaly detection.

    Returns:
        Structured dict with list of detected errors.
    """
    try:
        all_metrics = {**raw_metrics, **derived_metrics}
        errors: list[dict[str, Any]] = []

        errors.extend(_check_thresholds(all_metrics))
        errors.extend(_check_statistical_anomalies(all_metrics, past_records))
        errors.extend(_check_funnel_leaks(raw_metrics, derived_metrics))

        deviations = evaluation.get("deviations", {})
        errors.extend(_check_benchmark_deviations(deviations, all_metrics))

        errors.sort(key=lambda e: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(e.get("severity", "low"), 4))

        seen = set()
        unique_errors: list[dict[str, Any]] = []
        for err in errors:
            key = (err.get("type", ""), err.get("metric", ""))
            if key not in seen:
                seen.add(key)
                unique_errors.append(err)

        return {
            "status": "success",
            "errors": unique_errors,
            "error_count": len(unique_errors),
            "has_critical": any(e.get("severity") == "critical" for e in unique_errors),
            "model_note": "Mistral would provide richer contextual anomaly explanations",
        }
    except Exception as exc:
        return {
            "status": "error",
            "errors": [],
            "error_count": 0,
            "has_critical": False,
            "error": str(exc),
        }


def _check_thresholds(metrics: dict[str, float]) -> list[dict[str, Any]]:
    """Check metrics against static thresholds."""
    errors: list[dict[str, Any]] = []

    for error_type, config in _THRESHOLDS.items():
        metric_name = config["metric"]
        actual = metrics.get(metric_name)
        if actual is None:
            continue

        actual_f = float(actual)
        direction = config["direction"]
        critical_val = config["critical"]
        warning_val = config["warning"]
        template = config["detail_template"]

        triggered = False
        severity = "low"
        threshold_used = warning_val

        if direction == "below":
            if actual_f < critical_val:
                triggered = True
                severity = "critical"
                threshold_used = critical_val
            elif actual_f < warning_val:
                triggered = True
                severity = "medium"
                threshold_used = warning_val
        else:
            if actual_f > critical_val:
                triggered = True
                severity = "critical"
                threshold_used = critical_val
            elif actual_f > warning_val:
                triggered = True
                severity = "medium"
                threshold_used = warning_val

        if triggered:
            severity_word = "below" if direction == "below" else "above"
            detail = template.format(
                actual=round(actual_f, 2),
                threshold=round(threshold_used, 2),
                severity_word=severity_word,
            )
            errors.append({
                "type": error_type,
                "severity": severity,
                "detail": detail,
                "metric": metric_name,
                "actual": round(actual_f, 4),
                "threshold": round(threshold_used, 4),
            })

    return errors


def _check_statistical_anomalies(
    metrics: dict[str, float],
    past_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect statistical outliers by comparing against historical distributions."""
    errors: list[dict[str, Any]] = []
    if len(past_records) < 3:
        return errors

    history_metrics: dict[str, list[float]] = {}
    for record in past_records:
        result = record.get("result", {})
        derived = record.get("derived_metrics", {})
        source = {**result, **derived}
        for key, val in source.items():
            if isinstance(val, (int, float)):
                if key not in history_metrics:
                    history_metrics[key] = []
                history_metrics[key].append(float(val))

    for metric_name, actual in metrics.items():
        if not isinstance(actual, (int, float)):
            continue
        hist_values = history_metrics.get(metric_name, [])
        if len(hist_values) < 3:
            continue

        mean = sum(hist_values) / len(hist_values)
        variance = sum((v - mean) ** 2 for v in hist_values) / len(hist_values)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std == 0.0:
            continue

        z_score = (float(actual) - mean) / std

        if abs(z_score) > 3.0:
            direction = "unusually low" if z_score < 0 else "unusually high"
            errors.append({
                "type": "statistical_anomaly",
                "severity": "high",
                "detail": f"{metric_name} value of {round(float(actual), 2)} is {direction} "
                          f"(z-score: {round(z_score, 2)}, mean: {round(mean, 2)}, std: {round(std, 2)})",
                "metric": metric_name,
                "actual": round(float(actual), 4),
                "threshold": round(mean + 3.0 * std if z_score > 0 else mean - 3.0 * std, 4),
            })
        elif abs(z_score) > 2.0:
            direction = "below average" if z_score < 0 else "above average"
            errors.append({
                "type": "statistical_deviation",
                "severity": "medium",
                "detail": f"{metric_name} is notably {direction} "
                          f"(z-score: {round(z_score, 2)}, mean: {round(mean, 2)})",
                "metric": metric_name,
                "actual": round(float(actual), 4),
                "threshold": round(mean, 4),
            })

    return errors


def _check_funnel_leaks(
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
) -> list[dict[str, Any]]:
    """Detect funnel inefficiencies (views -> clicks -> sales)."""
    errors: list[dict[str, Any]] = []

    views = raw_metrics.get("views", 0)
    clicks = raw_metrics.get("clicks", 0)
    sales = raw_metrics.get("sales", 0)

    if views > 100 and clicks == 0:
        errors.append({
            "type": "funnel_break_views_to_clicks",
            "severity": "critical",
            "detail": f"{int(views)} views but zero clicks — complete funnel break at attention stage",
            "metric": "clicks",
            "actual": 0.0,
            "threshold": 1.0,
        })

    if clicks > 20 and sales == 0:
        errors.append({
            "type": "funnel_break_clicks_to_sales",
            "severity": "high",
            "detail": f"{int(clicks)} clicks but zero sales — funnel breaks at conversion stage",
            "metric": "sales",
            "actual": 0.0,
            "threshold": 1.0,
        })

    ctr = derived_metrics.get("ctr", 0.0)
    conv = derived_metrics.get("conversion_rate", 0.0)
    if ctr > 5.0 and conv < 1.0 and clicks > 10:
        errors.append({
            "type": "funnel_efficiency_mismatch",
            "severity": "medium",
            "detail": f"High CTR ({round(ctr, 1)}%) but very low conversion ({round(conv, 1)}%) — "
                      f"landing page or offer likely misaligned with ad promise",
            "metric": "conversion_rate",
            "actual": round(conv, 4),
            "threshold": 1.0,
        })

    return errors


def _check_benchmark_deviations(
    deviations: dict[str, float],
    metrics: dict[str, float],
) -> list[dict[str, Any]]:
    """Flag metrics that deviate severely from benchmarks."""
    errors: list[dict[str, Any]] = []

    for metric, deviation in deviations.items():
        if deviation < -0.6:
            errors.append({
                "type": "severe_underperformance",
                "severity": "high",
                "detail": f"{metric} is {round(abs(deviation) * 100, 1)}% below benchmark",
                "metric": metric,
                "actual": round(metrics.get(metric, 0.0), 4),
                "threshold": 0.0,
            })

    return errors
