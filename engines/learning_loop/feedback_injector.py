"""Learning Loop — feedback injector.

Formats improvements and analysis into a structured feedback payload
ready for consumption by the decision system.

Model note: Would use Qwen for structured output formatting.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def inject_feedback(
    task: str,
    decision: str,
    evaluation: dict[str, Any],
    errors: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    insights: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format analysis results into a feedback payload for the decision system.

    Args:
        task: The task that was executed.
        decision: The decision that led to execution.
        evaluation: Evaluation result from the evaluator.
        errors: Detected errors from error detector.
        improvements: Improvement suggestions from improvement engine.
        insights: Generated insights from insight generator.
        patterns: Detected patterns from pattern analyzer.

    Returns:
        Structured dict with feedback payload.
    """
    try:
        performance = evaluation.get("performance", "unknown")
        score = evaluation.get("score", 0.0)

        top_improvements = _select_top_improvements(improvements, max_count=5)

        priority_actions = _extract_priority_actions(
            errors, improvements, insights,
        )

        decision_guidance = _build_decision_guidance(
            performance, errors, patterns, score,
        )

        feedback_confidence = _compute_feedback_confidence(
            evaluation, errors, patterns, improvements,
        )

        feedback_payload: dict[str, Any] = {
            "source_task": task,
            "source_decision": decision,
            "performance_label": performance,
            "performance_score": round(score, 4),
            "errors": copy.deepcopy(errors),
            "top_improvements": top_improvements,
            "priority_actions": priority_actions,
            "decision_guidance": decision_guidance,
            "insight_summary": _summarize_insights(insights),
            "pattern_summary": _summarize_patterns(patterns),
            "confidence": round(feedback_confidence, 4),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        return {
            "status": "success",
            "feedback": feedback_payload,
            "model_note": "Qwen would produce a more refined structured output format",
        }
    except Exception as exc:
        return {
            "status": "error",
            "feedback": {
                "source_task": task,
                "source_decision": decision,
                "performance_label": "unknown",
                "performance_score": 0.0,
                "errors": [],
                "top_improvements": [],
                "priority_actions": [],
                "decision_guidance": {},
                "insight_summary": [],
                "pattern_summary": [],
                "confidence": 0.0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "error": str(exc),
        }


def _select_top_improvements(
    improvements: list[dict[str, Any]],
    max_count: int = 5,
) -> list[dict[str, Any]]:
    """Select the most impactful improvements for the decision system."""
    if not improvements:
        return []

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_imps = sorted(
        improvements,
        key=lambda i: (
            priority_order.get(i.get("priority", "low"), 4),
            -i.get("confidence", 0.0),
        ),
    )

    selected = copy.deepcopy(sorted_imps[:max_count])
    for imp in selected:
        imp.pop("rationale", None)

    return selected


def _extract_priority_actions(
    errors: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    insights: list[dict[str, Any]],
) -> list[str]:
    """Extract the most urgent actions as simple strings."""
    actions: list[str] = []

    for error in errors:
        if error.get("severity") == "critical":
            actions.append(f"CRITICAL: Address {error.get('type', 'issue')} - {error.get('detail', '')}")

    for imp in improvements:
        if imp.get("priority") == "critical":
            actions.append(f"ACTION: {imp.get('action', '')}")

    for insight in insights:
        if insight.get("priority") == "critical":
            actions.append(f"INSIGHT: {insight.get('insight', '')}")

    return actions[:10]


def _build_decision_guidance(
    performance: str,
    errors: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    score: float,
) -> dict[str, Any]:
    """Build guidance for the decision system based on all analysis."""
    has_critical = any(e.get("severity") == "critical" for e in errors)
    has_declining = any(p.get("type") == "declining_trend" for p in patterns)
    has_recurring = any(p.get("type") == "recurring_error" for p in patterns)

    if has_critical or performance == "poor":
        recommendation = "change_strategy"
        urgency = "immediate"
    elif has_declining or has_recurring or performance == "below_average":
        recommendation = "adjust_approach"
        urgency = "soon"
    elif performance == "above_average":
        recommendation = "scale_and_optimize"
        urgency = "normal"
    else:
        recommendation = "monitor_and_iterate"
        urgency = "normal"

    repeat_decision = performance in ("above_average",) and not has_critical
    scale_up = performance == "above_average" and score > 0.75 and not has_critical

    return {
        "recommendation": recommendation,
        "urgency": urgency,
        "repeat_decision": repeat_decision,
        "scale_up": scale_up,
        "error_count": len(errors),
        "critical_error_count": sum(1 for e in errors if e.get("severity") == "critical"),
    }


def _summarize_insights(insights: list[dict[str, Any]]) -> list[str]:
    """Summarize insights as a list of strings for the decision system."""
    return [i.get("insight", "") for i in insights if i.get("insight")][:8]


def _summarize_patterns(patterns: list[dict[str, Any]]) -> list[str]:
    """Summarize patterns as a list of strings for the decision system."""
    return [
        f"[{p.get('type', 'unknown')}] {p.get('detail', '')}"
        for p in patterns
        if p.get("detail")
    ][:8]


def _compute_feedback_confidence(
    evaluation: dict[str, Any],
    errors: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
) -> float:
    """Compute overall confidence in the feedback payload."""
    base = 0.5

    eval_score = evaluation.get("score", 0.5)
    if eval_score > 0.0:
        base += 0.1

    if errors:
        base += min(0.1, len(errors) * 0.02)

    if patterns:
        high_conf_patterns = [p for p in patterns if p.get("confidence", 0) > 0.6]
        base += min(0.15, len(high_conf_patterns) * 0.05)

    if improvements:
        base += min(0.1, len(improvements) * 0.02)

    pattern_confidences = [p.get("confidence", 0.5) for p in patterns]
    if pattern_confidences:
        avg_pattern_conf = sum(pattern_confidences) / len(pattern_confidences)
        base = base * 0.7 + avg_pattern_conf * 0.3

    return max(0.1, min(0.95, base))
