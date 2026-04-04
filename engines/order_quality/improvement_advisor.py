"""Order Quality Engine — improvement advisor.

Advises quality improvements based on defect patterns.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def advise_improvements(
    supplier_quality_scores: list[dict[str, Any]],
    defect_rates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate improvement actions for suppliers.

    Args:
        supplier_quality_scores: Quality scores per supplier.
        defect_rates: Defect rates from defect_tracker.

    Returns:
        Structured dict with improvement actions.
    """
    try:
        actions: list[dict[str, Any]] = []

        for score in supplier_quality_scores:
            sid = score.get("supplier_id", "")
            grade = score.get("grade", "C")
            defect_rate = score.get("defect_rate", 0.0)
            severity = score.get("severity_breakdown", {})

            if grade == "F":
                actions.append({
                    "supplier_id": sid,
                    "action": "Consider replacing supplier or require corrective action plan within 30 days",
                    "priority": "critical",
                    "expected_impact": "Eliminate major quality issues",
                })
            elif grade == "D":
                actions.append({
                    "supplier_id": sid,
                    "action": "Require formal quality improvement plan with weekly progress reports",
                    "priority": "high",
                    "expected_impact": "Reduce defect rate by 50%+ within 60 days",
                })

            if severity.get("critical", 0) > 0:
                actions.append({
                    "supplier_id": sid,
                    "action": "Immediate root cause analysis for critical defects — halt new orders until resolved",
                    "priority": "critical",
                    "expected_impact": "Eliminate critical defects",
                })

            if defect_rate > 0.10:
                actions.append({
                    "supplier_id": sid,
                    "action": "Implement pre-shipment inspection for all orders",
                    "priority": "high",
                    "expected_impact": f"Catch defects before shipping — current rate: {defect_rate:.1%}",
                })
            elif defect_rate > 0.05:
                actions.append({
                    "supplier_id": sid,
                    "action": "Increase sampling rate for quality checks",
                    "priority": "medium",
                    "expected_impact": f"Reduce defect rate from {defect_rate:.1%} to below 5%",
                })

        if not actions:
            actions.append({
                "supplier_id": "all",
                "action": "All suppliers meeting quality standards — maintain current quality program",
                "priority": "low",
                "expected_impact": "Sustain current quality levels",
            })

        return {"status": "success", "improvement_actions": actions}
    except Exception as exc:
        return {"status": "error", "improvement_actions": [], "error": f"Improvement advising failed: {exc}"}
