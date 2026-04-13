"""Retargeting sequence planning — escalating message + offer over 30 days."""
from __future__ import annotations

from typing import Any

RETARGETING_SEQUENCE = [
    {"days": (1, 3), "message": "product_reminder", "cta": "Still interested?", "discount": 0},
    {"days": (4, 7), "message": "social_proof", "cta": "See what others say", "discount": 0},
    {"days": (8, 14), "message": "urgency", "cta": "Limited stock", "discount": 0.05},
    {"days": (15, 21), "message": "incentive", "cta": "Special offer for you", "discount": 0.10},
    {"days": (22, 30), "message": "last_chance", "cta": "Final reminder", "discount": 0.15},
]


def plan_retargeting_sequence(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """Plan a multi-stage retargeting sequence.

    Best practice: escalating message + offer over 30 days.
    """
    return {
        "sequence": RETARGETING_SEQUENCE,
        "total_stages": len(RETARGETING_SEQUENCE),
        "duration_days": 30,
        "expected_recovery_rate": "15-25% of abandoned visitors",
        "key_principle": "Escalate urgency and incentive over time — don't lead with discount",
    }
