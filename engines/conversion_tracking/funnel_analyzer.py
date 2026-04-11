"""Conversion Tracking Engine — funnel analyzer.

Analyzes conversion funnels by tracking progression through stages.
Identifies drop-off points and computes stage-by-stage conversion rates.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default funnel stage ordering
# ---------------------------------------------------------------------------

_DEFAULT_FUNNEL_STAGES = [
    "page_view",
    "add_to_cart",
    "checkout_start",
    "checkout_complete",
    "purchase",
]


def analyze_funnel(
    tracked_events: list[dict[str, Any]],
    touchpoints: list[dict[str, Any]],
    funnel_stages: list[str] | None = None,
) -> dict[str, Any]:
    """Analyze the conversion funnel from tracked events.

    Args:
        tracked_events: List of validated tracked events.
        touchpoints: List of marketing touchpoints.
        funnel_stages: Ordered list of funnel stage names. Uses default if empty.

    Returns:
        Structured dict with funnel analysis.
    """
    try:
        tracked_events = copy.deepcopy(tracked_events)
        stages = funnel_stages if funnel_stages else _DEFAULT_FUNNEL_STAGES

        # Count unique sessions/customers at each stage
        stage_customers: dict[str, set[str]] = {stage: set() for stage in stages}

        for event in tracked_events:
            if not event.get("is_valid", False):
                continue
            event_type = str(event.get("event_type", ""))
            customer_id = str(event.get("customer_id", event.get("session_id", "")))

            if event_type in stage_customers and customer_id:
                stage_customers[event_type].add(customer_id)

        # Also count touchpoint impressions as top-of-funnel
        if "page_view" in stage_customers:
            for tp in touchpoints:
                cid = str(tp.get("customer_id", ""))
                if cid:
                    stage_customers["page_view"].add(cid)

        # Build funnel stages with rates
        funnel_stages_output: list[dict[str, Any]] = []
        drop_offs: dict[str, float] = {}
        prev_count = 0

        for i, stage in enumerate(stages):
            count = len(stage_customers.get(stage, set()))

            if i == 0:
                rate = 1.0
                drop_off = 0.0
            else:
                rate = round(count / prev_count, 4) if prev_count > 0 else 0.0
                drop_off = round(1.0 - rate, 4)

            funnel_stages_output.append({
                "name": stage,
                "count": count,
                "rate": rate,
                "drop_off": drop_off,
            })

            if drop_off > 0:
                drop_offs[f"{stages[i-1]}_to_{stage}"] = drop_off

            prev_count = count if count > 0 else prev_count

        # Overall conversion rate (top to bottom)
        top_count = len(stage_customers.get(stages[0], set())) if stages else 0
        bottom_count = len(stage_customers.get(stages[-1], set())) if stages else 0
        overall_rate = round(bottom_count / top_count, 4) if top_count > 0 else 0.0

        # Find biggest drop-off
        biggest_drop = ""
        biggest_drop_val = 0.0
        for transition, val in drop_offs.items():
            if val > biggest_drop_val:
                biggest_drop_val = val
                biggest_drop = transition

        funnel = {
            "stages": funnel_stages_output,
            "drop_offs": drop_offs,
            "overall_conversion_rate": overall_rate,
            "biggest_drop_off": biggest_drop,
        }

        return {
            "status": "success",
            "funnel": funnel,
        }
    except Exception as exc:
        return {
            "status": "error",
            "funnel": {},
            "error": f"Funnel analysis failed: {exc}",
        }
