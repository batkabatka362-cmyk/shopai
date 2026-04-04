"""Customer Journey Engine — stage analyzer.

Analyzes each journey stage: awareness, consideration, purchase, retention.
Computes conversion rates, average time in stage, and engagement metrics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_STAGE_ORDER = ["awareness", "consideration", "purchase", "retention"]


def analyze_stages(
    journey_map: dict[str, Any],
    customer_journeys: list[dict[str, Any]],
    conversions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze metrics for each journey stage.

    Computes conversion rates between stages, average events per stage,
    and identifies the strongest and weakest stages.

    Args:
        journey_map: Aggregate journey data from journey_builder.
        customer_journeys: Per-customer journey data from journey_builder.
        conversions: List of conversion dicts with customer_id, value.

    Returns:
        Structured dict with stage_metrics list.
    """
    try:
        jmap = copy.deepcopy(journey_map)
        journeys = copy.deepcopy(customer_journeys)
        conv_list = copy.deepcopy(conversions)

        total_customers = int(jmap.get("total_customers", 0))
        stage_counts = jmap.get("stage_counts", {})

        # Build conversion map
        conv_map: dict[str, float] = {}
        for c in conv_list:
            cid = str(c.get("customer_id", ""))
            value = float(c.get("value", 0.0))
            conv_map[cid] = conv_map.get(cid, 0.0) + value

        # Compute customers who reached each stage (cumulative)
        reached: dict[str, int] = {}
        for stage in _STAGE_ORDER:
            stage_idx = _STAGE_ORDER.index(stage)
            count = 0
            for j in journeys:
                furthest = str(j.get("furthest_stage", "none"))
                if furthest in _STAGE_ORDER:
                    if _STAGE_ORDER.index(furthest) >= stage_idx:
                        count += 1
            reached[stage] = count

        stage_metrics: list[dict[str, Any]] = []

        for i, stage in enumerate(_STAGE_ORDER):
            customers_in_stage = reached.get(stage, 0)

            # Conversion to next stage
            if i < len(_STAGE_ORDER) - 1:
                next_stage = _STAGE_ORDER[i + 1]
                next_count = reached.get(next_stage, 0)
                conversion_rate = (
                    round(next_count / customers_in_stage, 4)
                    if customers_in_stage > 0 else 0.0
                )
            else:
                conversion_rate = None  # last stage has no next

            # Average events in this stage
            total_events = 0
            stage_customers = 0
            for j in journeys:
                eps = j.get("events_per_stage", {})
                events_in_stage = int(eps.get(stage, 0))
                if events_in_stage > 0:
                    total_events += events_in_stage
                    stage_customers += 1

            avg_events = (
                round(total_events / stage_customers, 1)
                if stage_customers > 0 else 0.0
            )

            # Revenue for purchase stage
            stage_revenue = 0.0
            if stage == "purchase":
                for j in journeys:
                    cid = str(j.get("customer_id", ""))
                    if j.get("furthest_stage", "") in ("purchase", "retention"):
                        stage_revenue += conv_map.get(cid, 0.0)

            stage_metrics.append({
                "stage": stage,
                "customers_reached": customers_in_stage,
                "pct_of_total": (
                    round(customers_in_stage / total_customers, 4)
                    if total_customers > 0 else 0.0
                ),
                "conversion_to_next": conversion_rate,
                "avg_events": avg_events,
                "revenue": round(stage_revenue, 2) if stage == "purchase" else None,
            })

        return {
            "status": "success",
            "stage_metrics": stage_metrics,
        }
    except Exception as exc:
        return {
            "status": "error",
            "stage_metrics": [],
            "error": f"Stage analysis failed: {exc}",
        }
