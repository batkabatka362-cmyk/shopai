"""Inventory autonomy status surface (Wave 136)."""
from __future__ import annotations

from dataclasses import dataclass, field

from engines.inventory_autonomy.inventory_health import (
    analyze_inventory_health,
)
from engines.inventory_autonomy.inventory_log import (
    recent_events,
)
from engines.inventory_autonomy.inventory_state import (
    get_state,
)


@dataclass
class InventoryStatusReport:
    window_hours: float
    store_id: str | None = None
    total_events: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    total_units_reordered: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    health_verdict: str = "healthy"
    health_failure_ratio: float = 0.0
    paused: bool = False
    pause_reason: str = ""
    verdict: str = "healthy"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def get_inventory_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> InventoryStatusReport:
    report = InventoryStatusReport(
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
            try:
                delta = int(
                    r.get("new_quantity", 0) or 0,
                ) - int(r.get("prior_quantity", 0) or 0)
            except (TypeError, ValueError):
                delta = 0
            report.total_units_reordered += max(0, delta)
        else:
            report.skipped_count += 1

    health = analyze_inventory_health(
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
            f"inventory auto-pause active: "
            f"{report.pause_reason or '(no reason)'}"
        )
        report.next_action = (
            "Resume via `shopai inventory-resume`."
        )
    elif report.health_verdict == "critical":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"inventory failure ratio "
            f"{report.health_failure_ratio:.0%} >= critical"
        )
        report.next_action = (
            "`shopai inventory-health --apply-bridge`."
        )
    elif report.health_verdict == "degraded":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"inventory failure ratio "
            f"{report.health_failure_ratio:.0%} above warn"
        )
        report.next_action = "Monitor closely."
    elif report.total_events == 0:
        report.verdict = "quiet"
        report.verdict_reasons.append(
            "no inventory mutations in window"
        )
        report.next_action = (
            "Enable autonomous reorder via "
            "data.apply_inventory_reorders=True in the engine."
        )
    else:
        report.verdict = "healthy"
        report.verdict_reasons.append(
            f"{report.applied_count} reorder(s) applied, "
            f"+{report.total_units_reordered} units"
        )
        report.next_action = "Monitor via daily-brief."
    return report
