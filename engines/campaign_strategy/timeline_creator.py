"""Campaign Strategy Engine — timeline creator.

Creates campaign timeline with milestones.
"""
from __future__ import annotations

from typing import Any


def create_timeline(
    phases: list[dict[str, Any]],
    duration_days: int,
) -> dict[str, Any]:
    """Create campaign timeline with milestones."""
    try:
        milestones: list[dict[str, Any]] = []
        current_day = 0

        # Pre-launch milestone
        milestones.append({
            "day": 0,
            "description": "Campaign launch — all creative assets and tracking live",
            "phase": "launch",
            "deliverable": "Campaign go-live",
        })

        for phase in phases:
            phase_name = phase.get("name", "")
            phase_days = int(phase.get("duration_days", 7))

            # Phase start
            if current_day > 0:
                milestones.append({
                    "day": current_day,
                    "description": f"Begin {phase_name} phase",
                    "phase": phase_name,
                    "deliverable": f"{phase_name.title()} creative and targeting activated",
                })

            # Mid-phase check-in
            mid_day = current_day + phase_days // 2
            if phase_days > 5:
                milestones.append({
                    "day": mid_day,
                    "description": f"Mid-{phase_name} performance review",
                    "phase": phase_name,
                    "deliverable": "Performance report and optimization recommendations",
                })

            current_day += phase_days

        # Campaign end
        milestones.append({
            "day": duration_days,
            "description": "Campaign wrap-up — final performance analysis",
            "phase": "wrap_up",
            "deliverable": "Final campaign report with ROI analysis",
        })

        # Expected results (aggregate from phases)
        total_reach = 0
        total_conversions = 0
        for phase in phases:
            # Rough estimates
            total_reach += int(phase.get("duration_days", 7)) * 500
            total_conversions += int(phase.get("duration_days", 7)) * 5

        expected_results = {
            "total_reach": total_reach,
            "total_conversions": total_conversions,
            "expected_roas": round(total_conversions * 50 / max(1, duration_days * 10), 2),
            "cost_per_acquisition": round(duration_days * 10 / max(total_conversions, 1), 2),
        }

        return {
            "status": "success",
            "milestones": milestones,
            "expected_results": expected_results,
        }
    except Exception as exc:
        return {"status": "error", "milestones": [], "expected_results": {}, "error": f"Timeline creation failed: {exc}"}
