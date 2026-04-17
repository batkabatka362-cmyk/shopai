"""Reliability-signal collector — stub.

Returns an empty health/dead-letter/cost snapshot. Real
implementation would aggregate adapter circuit-breaker state,
DLQ row counts, and spend totals so the controller can surface
``reliability_alert`` entries. Until those subsystems land, the
controller's try/except still wraps us as belt-and-braces.
"""
from __future__ import annotations

from typing import Any


def collect_reliability_signal() -> dict[str, Any]:
    return {
        "health": {"totals": {}, "unhealthy": [], "degraded": []},
        "deadletter": {"total_records": 0, "new_since_last": 0},
        "cost": {"total_usd": 0.0, "delta_usd": 0.0},
    }
