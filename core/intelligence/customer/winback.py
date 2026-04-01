"""Winback campaign candidate identification."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_int

logger = get_logger("intelligence.customer.winback")

# Winback sequence
WINBACK_SEQUENCE = [
    {"days_inactive": 30, "stage": "soft", "subject": "We miss you!", "offer": "none", "tone": "Friendly reminder"},
    {"days_inactive": 45, "stage": "value", "subject": "See what's new", "offer": "free_shipping", "tone": "Show new products + social proof"},
    {"days_inactive": 60, "stage": "incentive", "subject": "A gift for you", "offer": "15%_off", "tone": "Personalized discount"},
    {"days_inactive": 90, "stage": "last_chance", "subject": "Last chance: 25% off", "offer": "25%_off", "tone": "Urgency + biggest offer"},
    {"days_inactive": 120, "stage": "sunset", "subject": "Should we stop emailing?", "offer": "none", "tone": "Respect + final attempt"},
]


def identify_winback_candidates(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Identify customers for winback campaigns by stage."""
    candidates: dict[str, list] = {s["stage"]: [] for s in WINBACK_SEQUENCE}

    for customer in customers:
        if not isinstance(customer, dict):
            continue

        days_inactive = safe_int(customer.get("days_since_last_order", 0))
        order_count = safe_int(customer.get("orders_count", 0))
        if order_count == 0 or days_inactive < 30:
            continue

        name = customer.get("name", customer.get("email", "?"))
        for stage in WINBACK_SEQUENCE:
            if days_inactive >= stage["days_inactive"]:
                matching_stage = stage["stage"]

        for stage in WINBACK_SEQUENCE:
            if stage["days_inactive"] <= days_inactive < stage.get("_next", 999):
                candidates[stage["stage"]].append({
                    "name": name,
                    "days_inactive": days_inactive,
                    "past_orders": order_count,
                })
                break

    # Fill in _next thresholds for matching
    total_candidates = sum(len(v) for v in candidates.values())

    return {
        "total_winback_candidates": total_candidates,
        "by_stage": {
            stage: {
                "count": len(members),
                "offer": next(s["offer"] for s in WINBACK_SEQUENCE if s["stage"] == stage),
                "subject_line": next(s["subject"] for s in WINBACK_SEQUENCE if s["stage"] == stage),
            }
            for stage, members in candidates.items()
        },
        "sequence": WINBACK_SEQUENCE,
    }
