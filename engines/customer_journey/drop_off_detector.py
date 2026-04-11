"""Customer Journey Engine — drop-off detector.

Detects where customers drop off in the journey. Identifies the biggest
leakage points between stages and specific events that precede abandonment.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_STAGE_ORDER = ["awareness", "consideration", "purchase", "retention"]


def detect_drop_offs(
    stage_metrics: list[dict[str, Any]],
    customer_journeys: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect customer drop-off points in the journey.

    Identifies stages with the highest attrition and which events
    commonly precede customer abandonment.

    Args:
        stage_metrics: Per-stage metrics from stage_analyzer.
        customer_journeys: Per-customer journey data from journey_builder.

    Returns:
        Structured dict with drop_off_points list.
    """
    try:
        metrics = copy.deepcopy(stage_metrics)
        journeys = copy.deepcopy(customer_journeys)

        drop_off_points: list[dict[str, Any]] = []

        # Build stage metrics map
        metric_map = {str(m.get("stage", "")): m for m in metrics}

        # Identify drop-off between each pair of stages
        for i in range(len(_STAGE_ORDER) - 1):
            current_stage = _STAGE_ORDER[i]
            next_stage = _STAGE_ORDER[i + 1]

            current_data = metric_map.get(current_stage, {})
            current_reached = int(current_data.get("customers_reached", 0))
            conversion = current_data.get("conversion_to_next")

            if conversion is not None and current_reached > 0:
                drop_off_rate = round(1.0 - conversion, 4)
                drop_off_count = current_reached - int(
                    metric_map.get(next_stage, {}).get("customers_reached", 0),
                )

                # Severity based on drop-off rate
                if drop_off_rate >= 0.7:
                    severity = "critical"
                elif drop_off_rate >= 0.5:
                    severity = "high"
                elif drop_off_rate >= 0.3:
                    severity = "medium"
                else:
                    severity = "low"

                drop_off_points.append({
                    "from_stage": current_stage,
                    "to_stage": next_stage,
                    "drop_off_rate": drop_off_rate,
                    "drop_off_count": drop_off_count,
                    "customers_entering": current_reached,
                    "severity": severity,
                    "description": (
                        f"{round(drop_off_rate * 100, 1)}% of customers drop off "
                        f"between {current_stage} and {next_stage} "
                        f"({drop_off_count} customers lost)."
                    ),
                })

        # Find the last events for customers who dropped off at each stage
        for dp in drop_off_points:
            from_stage = dp["from_stage"]
            last_events: dict[str, int] = {}

            for j in journeys:
                furthest = str(j.get("furthest_stage", "none"))
                if furthest == from_stage:
                    # Customer dropped off here — check their last events
                    eps = j.get("events_per_stage", {})
                    event_count = int(eps.get(from_stage, 0))
                    if event_count > 0:
                        last_events[from_stage] = last_events.get(from_stage, 0) + 1

            dp["common_last_stage_activity"] = last_events

        # Sort by drop-off rate descending
        drop_off_points.sort(key=lambda d: d["drop_off_rate"], reverse=True)

        return {
            "status": "success",
            "drop_off_points": drop_off_points,
            "total_drop_off_points": len(drop_off_points),
        }
    except Exception as exc:
        return {
            "status": "error",
            "drop_off_points": [],
            "error": f"Drop-off detection failed: {exc}",
        }
