"""Learning Loop — improvement engine.

Produces concrete improvement suggestions with expected impact,
priority, and rationale based on insights, errors, and patterns.

Model note: Would use LLaMA for creative improvement generation.
"""
from __future__ import annotations

import copy
from typing import Any


_IMPROVEMENT_CATALOG: dict[str, dict[str, Any]] = {
    "low_ctr": {
        "action": "Revise ad creative and headlines to be more compelling and relevant to the target audience",
        "expected_impact": "CTR improvement of 30-80% based on industry A/B test data",
        "priority": "high",
        "rationale": "Low CTR indicates the creative is not resonating with the audience. "
                     "Headline and visual changes typically yield the fastest CTR gains.",
    },
    "low_conversion": {
        "action": "Optimize landing page: improve value proposition clarity, add social proof, simplify checkout",
        "expected_impact": "Conversion rate improvement of 20-50%",
        "priority": "high",
        "rationale": "Traffic is arriving but not converting. The landing experience "
                     "must better match user expectations set by the ad.",
    },
    "high_bounce": {
        "action": "Improve page load speed, ensure mobile responsiveness, and align page content with ad promise",
        "expected_impact": "Bounce rate reduction of 15-30%",
        "priority": "high",
        "rationale": "High bounce rate means visitors leave immediately. "
                     "Speed, relevance, and design are the primary drivers.",
    },
    "high_cpa": {
        "action": "Narrow targeting to higher-intent audiences and implement negative keyword lists",
        "expected_impact": "CPA reduction of 20-40%",
        "priority": "high",
        "rationale": "Acquisition costs are too high relative to value. "
                     "Tighter targeting reduces wasted spend on low-intent users.",
    },
    "negative_roas": {
        "action": "Pause underperforming ad sets, reallocate budget to top performers, test new audience segments",
        "expected_impact": "ROAS improvement of 50-150%",
        "priority": "critical",
        "rationale": "Negative ROAS means the campaign is losing money on every dollar spent. "
                     "Immediate reallocation is needed.",
    },
    "negative_profit": {
        "action": "Review pricing strategy, reduce cost channels, and focus on highest-margin products",
        "expected_impact": "Move from loss to breakeven or profitability within 1-2 cycles",
        "priority": "critical",
        "rationale": "Operating at a loss is unsustainable. Structural changes to cost "
                     "or pricing are required.",
    },
    "funnel_disconnect": {
        "action": "Align landing page messaging with ad creative, add product-specific landing pages",
        "expected_impact": "Conversion rate improvement of 25-60%",
        "priority": "high",
        "rationale": "Users click expecting one thing but find another. "
                     "Message match is the highest-leverage fix for this pattern.",
    },
    "declining_trend": {
        "action": "Refresh creative assets, test new audience segments, and review competitive positioning",
        "expected_impact": "Reverse the declining trend and stabilize performance within 2-3 cycles",
        "priority": "high",
        "rationale": "Declining performance often signals ad fatigue, market shift, "
                     "or increased competition.",
    },
    "recurring_error": {
        "action": "Implement systematic monitoring for the recurring issue and create automated guardrails",
        "expected_impact": "Prevent recurrence and reduce error frequency by 70-90%",
        "priority": "high",
        "rationale": "Repeated errors indicate a structural problem that needs a permanent fix, "
                     "not repeated manual intervention.",
    },
    "low_attention_capture": {
        "action": "Test bold visual formats (video, carousel), refine audience targeting, and improve ad copy hooks",
        "expected_impact": "CTR improvement of 40-100%",
        "priority": "medium",
        "rationale": "Low attention capture means the ad is not standing out in the feed. "
                     "Format and hook changes have the most impact.",
    },
    "landing_page_issue": {
        "action": "Redesign landing page with clear CTA, reduce form fields, add trust signals",
        "expected_impact": "Bounce rate reduction of 20-40%, conversion improvement of 15-35%",
        "priority": "high",
        "rationale": "Combined bounce and conversion issues point to landing page as the bottleneck.",
    },
    "zero_sales": {
        "action": "Validate product-market fit, review pricing against competitors, ensure checkout works correctly",
        "expected_impact": "Establish baseline sales and identify fundamental blockers",
        "priority": "critical",
        "rationale": "Zero sales with traffic suggests a fundamental issue with offer, price, or checkout.",
    },
    "chronically_underperforming_task": {
        "action": "Conduct a full strategy review: redefine objectives, test completely different approaches, or discontinue",
        "expected_impact": "Either find a viable approach or save resources by stopping",
        "priority": "critical",
        "rationale": "Chronic underperformance indicates the current approach is fundamentally flawed.",
    },
}


def generate_improvements(
    task: str,
    decision: str,
    evaluation: dict[str, Any],
    errors: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    insights: list[dict[str, Any]],
    derived_metrics: dict[str, float],
) -> dict[str, Any]:
    """Generate concrete improvement suggestions based on all analysis.

    Args:
        task: The task that was executed.
        decision: The decision that led to execution.
        evaluation: Evaluation result from the evaluator.
        errors: Detected errors from error detector.
        patterns: Detected patterns from pattern analyzer.
        insights: Generated insights from insight generator.
        derived_metrics: Computed derived metrics.

    Returns:
        Structured dict with improvement suggestions.
    """
    try:
        improvements: list[dict[str, Any]] = []

        improvements.extend(_improvements_from_errors(errors))
        improvements.extend(_improvements_from_patterns(patterns))
        improvements.extend(_improvements_from_evaluation(evaluation, derived_metrics))
        improvements.extend(_improvements_from_metrics(derived_metrics, task))

        improvements.sort(
            key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                i.get("priority", "low"), 4
            ),
        )

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for imp in improvements:
            key = imp.get("action", "")[:60]
            if key not in seen:
                seen.add(key)
                unique.append(imp)

        for idx, imp in enumerate(unique):
            imp["confidence"] = round(
                _compute_improvement_confidence(imp, len(errors), len(patterns), evaluation),
                4,
            )

        return {
            "status": "success",
            "improvements": unique,
            "improvement_count": len(unique),
            "model_note": "LLaMA would generate more creative and contextual improvement strategies",
        }
    except Exception as exc:
        return {
            "status": "error",
            "improvements": [],
            "improvement_count": 0,
            "error": str(exc),
        }


def _improvements_from_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate improvements targeting detected errors."""
    improvements: list[dict[str, Any]] = []

    for error in errors:
        etype = error.get("type", "")
        catalog_entry = _IMPROVEMENT_CATALOG.get(etype)

        if catalog_entry:
            improvements.append({
                "action": catalog_entry["action"],
                "expected_impact": catalog_entry["expected_impact"],
                "priority": catalog_entry["priority"],
                "confidence": 0.0,
                "rationale": catalog_entry["rationale"],
            })
        elif error.get("severity") in ("critical", "high"):
            improvements.append({
                "action": f"Investigate and resolve '{etype}': {error.get('detail', '')}",
                "expected_impact": "Depends on root cause analysis",
                "priority": error.get("severity", "medium"),
                "confidence": 0.0,
                "rationale": f"Error '{etype}' at {error.get('severity', 'unknown')} severity "
                             f"needs resolution to improve performance.",
            })

    return improvements


def _improvements_from_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate improvements targeting detected patterns."""
    improvements: list[dict[str, Any]] = []

    for pattern in patterns:
        ptype = pattern.get("type", "")
        catalog_entry = _IMPROVEMENT_CATALOG.get(ptype)

        if catalog_entry:
            improvements.append({
                "action": catalog_entry["action"],
                "expected_impact": catalog_entry["expected_impact"],
                "priority": catalog_entry["priority"],
                "confidence": 0.0,
                "rationale": catalog_entry["rationale"],
            })
        elif ptype == "decision_failure_correlation":
            improvements.append({
                "action": "Explore alternative decision strategies that have shown better historical outcomes",
                "expected_impact": "Performance improvement aligned with historical top performers",
                "priority": "high",
                "confidence": 0.0,
                "rationale": pattern.get("detail", "Historical data shows this decision type underperforms."),
            })
        elif ptype == "high_variance_task":
            improvements.append({
                "action": "Standardize execution process and add guardrails to reduce performance variability",
                "expected_impact": "More predictable outcomes with reduced downside risk",
                "priority": "medium",
                "confidence": 0.0,
                "rationale": pattern.get("detail", "High variance makes planning unreliable."),
            })

    return improvements


def _improvements_from_evaluation(
    evaluation: dict[str, Any],
    derived_metrics: dict[str, float],
) -> list[dict[str, Any]]:
    """Generate improvements based on evaluation gaps."""
    improvements: list[dict[str, Any]] = []
    deviations = evaluation.get("deviations", {})

    worst_metrics = sorted(deviations.items(), key=lambda kv: kv[1])[:3]

    for metric, dev in worst_metrics:
        if dev >= -0.15:
            continue

        gap_pct = round(abs(dev) * 100, 1)

        if metric == "ctr":
            improvements.append({
                "action": f"Improve CTR (currently {gap_pct}% below benchmark) through creative testing and audience refinement",
                "expected_impact": f"Close the {gap_pct}% gap to benchmark CTR levels",
                "priority": "high" if dev < -0.4 else "medium",
                "confidence": 0.0,
                "rationale": f"CTR is {gap_pct}% below benchmark, indicating creative or targeting issues.",
            })
        elif metric == "conversion_rate":
            improvements.append({
                "action": f"Improve conversion rate (currently {gap_pct}% below benchmark) through landing page optimization",
                "expected_impact": f"Close the {gap_pct}% gap to benchmark conversion levels",
                "priority": "high" if dev < -0.4 else "medium",
                "confidence": 0.0,
                "rationale": f"Conversion rate is {gap_pct}% below benchmark.",
            })
        elif metric == "profit_margin":
            improvements.append({
                "action": f"Improve profit margin (currently {gap_pct}% below benchmark) by optimizing costs or increasing prices",
                "expected_impact": f"Close the {gap_pct}% gap to benchmark margin levels",
                "priority": "high" if dev < -0.4 else "medium",
                "confidence": 0.0,
                "rationale": f"Profit margin is {gap_pct}% below benchmark.",
            })
        else:
            improvements.append({
                "action": f"Improve '{metric}' which is {gap_pct}% below benchmark",
                "expected_impact": f"Close the {gap_pct}% benchmark gap for {metric}",
                "priority": "medium",
                "confidence": 0.0,
                "rationale": f"{metric} underperforms benchmark by {gap_pct}%.",
            })

    return improvements


def _improvements_from_metrics(
    derived_metrics: dict[str, float],
    task: str,
) -> list[dict[str, Any]]:
    """Generate improvements based on absolute metric values."""
    improvements: list[dict[str, Any]] = []

    roas = derived_metrics.get("roas", 0.0)
    profit = derived_metrics.get("profit", 0.0)
    cpa = derived_metrics.get("cpa", 0.0)
    avg_order_value = derived_metrics.get("avg_order_value", 0.0)

    if 0 < roas < 1.0:
        improvements.append({
            "action": "Immediately reduce ad spend or pause campaign until ROAS exceeds 1.0x breakeven",
            "expected_impact": "Stop financial losses from unprofitable ad spend",
            "priority": "critical",
            "confidence": 0.0,
            "rationale": f"ROAS of {round(roas, 2)}x means losing money on every dollar spent.",
        })

    if cpa > 0 and avg_order_value > 0 and cpa > avg_order_value * 0.8:
        improvements.append({
            "action": "Reduce CPA through better targeting or increase AOV through upselling and bundling",
            "expected_impact": "Restore healthy CPA-to-AOV ratio for sustainable profitability",
            "priority": "high",
            "confidence": 0.0,
            "rationale": f"CPA (${round(cpa, 2)}) is dangerously close to or exceeds AOV (${round(avg_order_value, 2)}).",
        })

    return improvements


def _compute_improvement_confidence(
    improvement: dict[str, Any],
    error_count: int,
    pattern_count: int,
    evaluation: dict[str, Any],
) -> float:
    """Compute confidence score for an improvement suggestion."""
    base = 0.5

    priority = improvement.get("priority", "medium")
    if priority == "critical":
        base += 0.15
    elif priority == "high":
        base += 0.1

    if error_count > 0:
        base += min(0.1, error_count * 0.02)

    if pattern_count > 0:
        base += min(0.1, pattern_count * 0.03)

    score = evaluation.get("score", 0.5)
    if score < 0.3:
        base += 0.1
    elif score > 0.7:
        base -= 0.05

    return max(0.1, min(0.95, base))
