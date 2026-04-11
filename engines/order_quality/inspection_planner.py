"""Order Quality Engine — inspection planner.

Plans quality inspections based on supplier scores.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def plan_inspections(
    supplier_quality_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan quality inspections based on supplier quality scores.

    Args:
        supplier_quality_scores: Quality scores per supplier.

    Returns:
        Structured dict with inspection plans.
    """
    try:
        plans: list[dict[str, Any]] = []

        for score in supplier_quality_scores:
            grade = score.get("grade", "C")
            sid = score.get("supplier_id", "")
            name = score.get("supplier_name", "")
            severity = score.get("severity_breakdown", {})

            if grade in ("D", "F"):
                frequency = "every_shipment"
                priority = "critical"
            elif grade == "C":
                frequency = "weekly"
                priority = "high"
            elif grade == "B":
                frequency = "monthly"
                priority = "medium"
            else:
                frequency = "quarterly"
                priority = "low"

            focus: list[str] = []
            if severity.get("critical", 0) > 0:
                focus.append("critical_defect_root_cause")
            if severity.get("high", 0) > 0:
                focus.append("high_severity_patterns")
            if score.get("defect_rate", 0) > 0.05:
                focus.append("overall_process_quality")
            if not focus:
                focus.append("general_quality_audit")

            plans.append({
                "supplier_id": sid,
                "supplier_name": name,
                "inspection_frequency": frequency,
                "priority": priority,
                "focus_areas": focus,
            })

        return {"status": "success", "inspection_plan": plans}
    except Exception as exc:
        return {"status": "error", "inspection_plan": [], "error": f"Inspection planning failed: {exc}"}
