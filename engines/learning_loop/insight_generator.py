"""Learning Loop — insight generator.

Generates actionable insights from patterns, evaluation, and errors.
Synthesizes information into human-readable, prioritized insights.

Model note: Would use LLaMA for creative insight generation and synthesis.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_insights(
    task: str,
    decision: str,
    evaluation: dict[str, Any],
    errors: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
) -> dict[str, Any]:
    """Generate actionable insights from evaluation, errors, and patterns.

    Args:
        task: The task that was executed.
        decision: The decision that led to execution.
        evaluation: Evaluation result from the evaluator.
        errors: Detected errors from error detector.
        patterns: Detected patterns from pattern analyzer.
        raw_metrics: Raw collected metrics.
        derived_metrics: Computed derived metrics.

    Returns:
        Structured dict with prioritized insights.
    """
    try:
        insights: list[dict[str, Any]] = []

        insights.extend(_insights_from_evaluation(evaluation, task, decision))
        insights.extend(_insights_from_errors(errors))
        insights.extend(_insights_from_patterns(patterns))
        insights.extend(_insights_from_metrics(raw_metrics, derived_metrics, task))

        insights.sort(
            key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                i.get("priority", "low"), 4
            ),
        )

        seen_insights: set[str] = set()
        unique: list[dict[str, Any]] = []
        for ins in insights:
            key = ins.get("insight", "")[:80]
            if key not in seen_insights:
                seen_insights.add(key)
                unique.append(ins)

        return {
            "status": "success",
            "insights": unique,
            "insight_count": len(unique),
            "model_note": "LLaMA would generate richer narrative insights with strategic context",
        }
    except Exception as exc:
        return {
            "status": "error",
            "insights": [],
            "insight_count": 0,
            "error": str(exc),
        }


def _insights_from_evaluation(
    evaluation: dict[str, Any],
    task: str,
    decision: str,
) -> list[dict[str, Any]]:
    """Extract insights from the performance evaluation."""
    insights: list[dict[str, Any]] = []
    performance = evaluation.get("performance", "unknown")
    score = evaluation.get("score", 0.0)
    deviations = evaluation.get("deviations", {})
    benchmark_score = evaluation.get("benchmark_score", 0.5)
    history_score = evaluation.get("history_score", 0.5)

    if performance == "above_average":
        insights.append({
            "insight": f"The decision '{decision}' for task '{task}' performed above average "
                       f"(score: {round(score, 2)}). Identify what drove success to replicate it.",
            "source": "evaluation",
            "priority": "medium",
            "confidence": min(0.85, 0.5 + score * 0.4),
        })
    elif performance == "poor":
        insights.append({
            "insight": f"The decision '{decision}' for task '{task}' performed poorly "
                       f"(score: {round(score, 2)}). Immediate review and corrective action needed.",
            "source": "evaluation",
            "priority": "critical",
            "confidence": min(0.9, 0.6 + (1.0 - score) * 0.3),
        })
    elif performance == "below_average":
        insights.append({
            "insight": f"Below-average performance (score: {round(score, 2)}) for '{task}'. "
                       f"Review targeting, creative, or budget allocation.",
            "source": "evaluation",
            "priority": "high",
            "confidence": min(0.8, 0.5 + (0.5 - score) * 0.5),
        })

    if benchmark_score < 0.35:
        insights.append({
            "insight": "Performance is significantly below industry benchmarks. "
                       "The current approach may need a fundamental rethink rather than incremental changes.",
            "source": "evaluation_benchmark",
            "priority": "high",
            "confidence": 0.75,
        })

    if history_score < 0.35 and benchmark_score > 0.5:
        insights.append({
            "insight": "Performance has dropped compared to your own history even though it is "
                       "near industry benchmarks. Recent changes may have introduced a regression.",
            "source": "evaluation_history",
            "priority": "high",
            "confidence": 0.7,
        })

    strongest_metric = ""
    strongest_dev = -999.0
    weakest_metric = ""
    weakest_dev = 999.0
    for metric, dev in deviations.items():
        if dev > strongest_dev:
            strongest_dev = dev
            strongest_metric = metric
        if dev < weakest_dev:
            weakest_dev = dev
            weakest_metric = metric

    if strongest_metric and strongest_dev > 0.2:
        insights.append({
            "insight": f"Strongest metric relative to benchmark: '{strongest_metric}' "
                       f"(+{round(strongest_dev * 100, 1)}% above benchmark). Leverage this strength.",
            "source": "evaluation_deviation",
            "priority": "medium",
            "confidence": 0.7,
        })

    if weakest_metric and weakest_dev < -0.3:
        insights.append({
            "insight": f"Weakest metric relative to benchmark: '{weakest_metric}' "
                       f"({round(weakest_dev * 100, 1)}% below benchmark). Focus improvement efforts here.",
            "source": "evaluation_deviation",
            "priority": "high",
            "confidence": 0.75,
        })

    return insights


def _insights_from_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract insights from detected errors."""
    insights: list[dict[str, Any]] = []
    if not errors:
        return insights

    critical_errors = [e for e in errors if e.get("severity") == "critical"]
    high_errors = [e for e in errors if e.get("severity") == "high"]

    if critical_errors:
        error_types = ", ".join(set(e.get("type", "unknown") for e in critical_errors))
        insights.append({
            "insight": f"{len(critical_errors)} critical issue(s) detected: {error_types}. "
                       f"These require immediate attention before continuing this strategy.",
            "source": "error_detection",
            "priority": "critical",
            "confidence": 0.85,
        })

    if high_errors:
        error_types = ", ".join(set(e.get("type", "unknown") for e in high_errors))
        insights.append({
            "insight": f"{len(high_errors)} high-severity issue(s): {error_types}. "
                       f"Address these to prevent further performance degradation.",
            "source": "error_detection",
            "priority": "high",
            "confidence": 0.8,
        })

    funnel_errors = [e for e in errors if "funnel" in e.get("type", "")]
    if funnel_errors:
        insights.append({
            "insight": "Funnel analysis reveals drop-off issues. Review the user journey from "
                       "impression to conversion to identify where users disengage.",
            "source": "error_funnel",
            "priority": "high",
            "confidence": 0.75,
        })

    return insights


def _insights_from_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract insights from detected patterns."""
    insights: list[dict[str, Any]] = []
    if not patterns:
        return insights

    for pattern in patterns:
        ptype = pattern.get("type", "")
        detail = pattern.get("detail", "")
        confidence = pattern.get("confidence", 0.5)

        if ptype == "declining_trend":
            insights.append({
                "insight": f"Pattern detected: {detail}. Investigate root cause and consider "
                           f"strategy pivot before performance degrades further.",
                "source": "pattern_analysis",
                "priority": "high",
                "confidence": confidence,
            })
        elif ptype == "recurring_error":
            insights.append({
                "insight": f"Recurring issue: {detail}. This systematic problem needs a structural "
                           f"fix rather than ad-hoc patches.",
                "source": "pattern_analysis",
                "priority": "high",
                "confidence": confidence,
            })
        elif ptype == "decision_failure_correlation":
            insights.append({
                "insight": f"Historical pattern: {detail}. Consider alternative decision approaches "
                           f"that have shown better results.",
                "source": "pattern_analysis",
                "priority": "high",
                "confidence": confidence,
            })
        elif ptype == "decision_success_correlation":
            insights.append({
                "insight": f"Positive pattern: {detail}. Continue and refine this approach.",
                "source": "pattern_analysis",
                "priority": "medium",
                "confidence": confidence,
            })
        elif ptype == "funnel_disconnect":
            insights.append({
                "insight": f"Funnel pattern: {detail}. Aligning the landing experience with "
                           f"the ad promise should improve conversion.",
                "source": "pattern_analysis",
                "priority": "high",
                "confidence": confidence,
            })
        elif ptype in ("high_funnel_efficiency", "high_profitability_signal", "consistently_strong_task"):
            insights.append({
                "insight": f"Strength detected: {detail}. Document and scale what works.",
                "source": "pattern_analysis",
                "priority": "medium",
                "confidence": confidence,
            })
        elif ptype == "chronically_underperforming_task":
            insights.append({
                "insight": f"Systemic issue: {detail}. A fundamental approach change is warranted.",
                "source": "pattern_analysis",
                "priority": "critical",
                "confidence": confidence,
            })
        elif detail:
            insights.append({
                "insight": f"Pattern: {detail}",
                "source": "pattern_analysis",
                "priority": "medium",
                "confidence": confidence,
            })

    return insights


def _insights_from_metrics(
    raw_metrics: dict[str, float],
    derived_metrics: dict[str, float],
    task: str,
) -> list[dict[str, Any]]:
    """Extract insights directly from metric values."""
    insights: list[dict[str, Any]] = []
    all_m = {**raw_metrics, **derived_metrics}

    roas = all_m.get("roas", 0.0)
    cost = all_m.get("cost", 0.0)
    profit = all_m.get("profit", 0.0)
    views = all_m.get("views", 0)
    sales = all_m.get("sales", 0)
    cpa = all_m.get("cpa", 0.0)

    if cost > 0 and roas < 1.0:
        insights.append({
            "insight": f"Spending ${round(cost, 2)} but ROAS is only {round(roas, 2)}x. "
                       f"Every dollar spent returns less than a dollar. Pause or restructure.",
            "source": "metric_analysis",
            "priority": "critical",
            "confidence": 0.85,
        })
    elif cost > 0 and roas > 4.0:
        insights.append({
            "insight": f"ROAS of {round(roas, 1)}x is excellent. Consider increasing budget "
                       f"to scale returns while monitoring for diminishing returns.",
            "source": "metric_analysis",
            "priority": "medium",
            "confidence": 0.75,
        })

    if views > 1000 and sales == 0:
        insights.append({
            "insight": f"Despite {int(views)} views, zero sales were generated. The offer, "
                       f"pricing, or audience targeting may be fundamentally mismatched.",
            "source": "metric_analysis",
            "priority": "critical",
            "confidence": 0.9,
        })

    if sales > 0 and cpa > 0 and profit < 0:
        insights.append({
            "insight": f"Acquiring customers at ${round(cpa, 2)} each but operating at a loss "
                       f"(profit: ${round(profit, 2)}). Either reduce CPA or increase order value.",
            "source": "metric_analysis",
            "priority": "high",
            "confidence": 0.8,
        })

    return insights
