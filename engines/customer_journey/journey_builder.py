"""Customer Journey Engine — journey builder.

Builds a customer journey map from touchpoint data and events.
Maps customers through stages: awareness -> consideration -> purchase -> retention.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Journey stage definitions
# ---------------------------------------------------------------------------

_STAGE_ORDER = ["awareness", "consideration", "purchase", "retention"]

_EVENT_STAGE_MAP: dict[str, str] = {
    "page_view": "awareness",
    "ad_click": "awareness",
    "social_visit": "awareness",
    "search": "awareness",
    "product_view": "consideration",
    "add_to_cart": "consideration",
    "wishlist_add": "consideration",
    "compare": "consideration",
    "checkout_start": "purchase",
    "payment": "purchase",
    "order_complete": "purchase",
    "repeat_purchase": "retention",
    "review_submit": "retention",
    "referral": "retention",
    "subscription": "retention",
    "support_contact": "retention",
}


def build_journey(
    customers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    touchpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build customer journey maps from event and touchpoint data.

    Groups events by customer, orders them chronologically, and maps
    each customer's path through the journey stages.

    Args:
        customers: List of customer dicts with id, first_seen fields.
        events: List of event dicts with customer_id, event_type, timestamp.
        touchpoints: List of touchpoint dicts with name, stage.

    Returns:
        Structured dict with journey_map and customer_journeys.
    """
    try:
        cust_list = copy.deepcopy(customers)
        event_list = copy.deepcopy(events)
        tp_list = copy.deepcopy(touchpoints)

        # Build custom touchpoint-to-stage map
        tp_stage_map = dict(_EVENT_STAGE_MAP)
        for tp in tp_list:
            name = str(tp.get("name", ""))
            stage = str(tp.get("stage", ""))
            if name and stage in _STAGE_ORDER:
                tp_stage_map[name] = stage

        # Group events by customer
        customer_events: dict[str, list[dict[str, Any]]] = {}
        for event in event_list:
            cid = str(event.get("customer_id", ""))
            customer_events.setdefault(cid, []).append(event)

        # Sort each customer's events by timestamp
        for cid in customer_events:
            customer_events[cid].sort(
                key=lambda e: float(e.get("timestamp", 0)),
            )

        # Build per-customer journeys
        customer_journeys: list[dict[str, Any]] = []
        stage_counts: dict[str, int] = {s: 0 for s in _STAGE_ORDER}
        stage_transitions: dict[str, int] = {}

        cust_map = {str(c.get("id", "")): c for c in cust_list}

        for cid, evts in customer_events.items():
            stages_visited: list[str] = []
            stage_events: dict[str, list[dict[str, Any]]] = {
                s: [] for s in _STAGE_ORDER
            }

            for evt in evts:
                etype = str(evt.get("event_type", ""))
                stage = tp_stage_map.get(etype, "")
                if stage and stage in _STAGE_ORDER:
                    stage_events[stage].append(evt)
                    if not stages_visited or stages_visited[-1] != stage:
                        stages_visited.append(stage)

            # Furthest stage reached
            furthest_idx = -1
            for stage in stages_visited:
                idx = _STAGE_ORDER.index(stage)
                if idx > furthest_idx:
                    furthest_idx = idx

            furthest_stage = _STAGE_ORDER[furthest_idx] if furthest_idx >= 0 else "none"

            if furthest_idx >= 0:
                stage_counts[furthest_stage] = stage_counts.get(furthest_stage, 0) + 1

            # Track transitions
            for i in range(len(stages_visited) - 1):
                transition = f"{stages_visited[i]}->{stages_visited[i+1]}"
                stage_transitions[transition] = stage_transitions.get(transition, 0) + 1

            customer_journeys.append({
                "customer_id": cid,
                "stages_visited": stages_visited,
                "furthest_stage": furthest_stage,
                "total_events": len(evts),
                "events_per_stage": {
                    s: len(stage_events[s]) for s in _STAGE_ORDER
                },
            })

        return {
            "status": "success",
            "journey_map": {
                "total_customers": len(customer_journeys),
                "stage_counts": stage_counts,
                "stage_transitions": stage_transitions,
            },
            "customer_journeys": customer_journeys,
        }
    except Exception as exc:
        return {
            "status": "error",
            "journey_map": {},
            "customer_journeys": [],
            "error": f"Journey building failed: {exc}",
        }
