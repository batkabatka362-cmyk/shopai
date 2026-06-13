"""Fulfillment autonomy status surface (Wave 130).

Empire-wide aggregator mirroring marketing_status.py /
support_status.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engines.fulfillment_autonomy.fulfillment_health import (
    analyze_fulfillment_health,
)
from engines.fulfillment_autonomy.fulfillment_log import (
    recent_events,
)
from engines.fulfillment_autonomy.fulfillment_state import (
    get_state,
)


@dataclass
class FulfillmentStatusReport:
    window_hours: float
    store_id: str | None = None
    total_events: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    health_verdict: str = "healthy"
    health_failure_ratio: float = 0.0
    paused: bool = False
    pause_reason: str = ""
    verdict: str = "healthy"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def get_fulfillment_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> FulfillmentStatusReport:
    """Build the empire-wide fulfillment autonomy report."""
    report = FulfillmentStatusReport(
        window_hours=window_hours,
        store_id=store_id,
    )
    rows = recent_events(
        window_hours=window_hours, store_id=store_id,
    )
    report.total_events = len(rows)
    for r in rows:
        status = r.get("status", "")
        report.by_status[status] = (
            report.by_status.get(status, 0) + 1
        )
        if r.get("applied") is True:
            report.applied_count += 1
        else:
            report.skipped_count += 1

    health = analyze_fulfillment_health(
        window_hours=window_hours,
    )
    report.health_verdict = health.verdict
    report.health_failure_ratio = health.failure_ratio

    state = get_state()
    report.paused = state.paused
    report.pause_reason = state.reason

    if report.paused:
        report.verdict = "paused"
        report.verdict_reasons.append(
            f"fulfillment auto-pause active: "
            f"{report.pause_reason or '(no reason)'}"
        )
        report.next_action = (
            "Resume via `shopai fulfillment-resume`."
        )
    elif report.health_verdict == "critical":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"fulfillment failure ratio "
            f"{report.health_failure_ratio:.0%} >= critical"
        )
        report.next_action = (
            "`shopai fulfillment-health --apply-bridge`."
        )
    elif report.health_verdict == "degraded":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"fulfillment failure ratio "
            f"{report.health_failure_ratio:.0%} above warn"
        )
        report.next_action = "Monitor closely."
    elif report.total_events == 0:
        report.verdict = "quiet"
        report.verdict_reasons.append(
            "no fulfillment routes in window"
        )
        report.next_action = (
            "Enable autonomous routing via "
            "data.apply_fulfillment_routes=True in the engine "
            "inputs."
        )
    else:
        report.verdict = "healthy"
        report.verdict_reasons.append(
            f"{report.applied_count} route(s) applied"
        )
        report.next_action = "Monitor via daily-brief."
    return report
