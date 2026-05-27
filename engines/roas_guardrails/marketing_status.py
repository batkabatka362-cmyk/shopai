"""Marketing autonomy status surface (Wave 113).

Aggregates the Wave 110-112 substrate into one operator-facing
report. Same shape as ``customer_support/support_status.py``.

Surfaces:
  - Budget activity (count + status distribution)
  - Budget health verdict + failure ratio
  - Budget pause state
  - Aggregate verdict (paused / degraded / quiet / healthy)
  - Next-action hint
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engines.roas_guardrails.ad_spend_log import recent_events
from engines.roas_guardrails.budget_health import (
    analyze_budget_health,
)
from engines.roas_guardrails.budget_state import get_state


@dataclass
class MarketingStatusReport:
    window_hours: float
    store_id: str | None = None
    total_events: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    cuts_count: int = 0
    pauses_count: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    health_verdict: str = "healthy"
    health_failure_ratio: float = 0.0
    paused: bool = False
    pause_reason: str = ""
    verdict: str = "healthy"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def get_marketing_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> MarketingStatusReport:
    """Build the empire-wide marketing autonomy report."""
    report = MarketingStatusReport(
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
            if r.get("action") == "cut":
                report.cuts_count += 1
            elif r.get("action") == "pause":
                report.pauses_count += 1
        else:
            report.skipped_count += 1

    health = analyze_budget_health(window_hours=window_hours)
    report.health_verdict = health.verdict
    report.health_failure_ratio = health.failure_ratio

    state = get_state()
    report.paused = state.paused
    report.pause_reason = state.reason

    # Aggregate verdict (same severity order as support-status)
    if report.paused:
        report.verdict = "paused"
        report.verdict_reasons.append(
            f"budget auto-pause active: "
            f"{report.pause_reason or '(no reason)'}"
        )
        report.next_action = (
            "Resume via `shopai marketing-resume` once the "
            "underlying issue is addressed."
        )
    elif report.health_verdict == "critical":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"budget failure ratio "
            f"{report.health_failure_ratio:.0%} >= critical"
        )
        report.next_action = (
            "Run `shopai marketing-health --apply-bridge` to "
            "auto-pause; investigate adapter_failed rows."
        )
    elif report.health_verdict == "degraded":
        report.verdict = "degraded"
        report.verdict_reasons.append(
            f"budget failure ratio "
            f"{report.health_failure_ratio:.0%} above warn"
        )
        report.next_action = (
            "Monitor closely; consider tightening "
            "SHOPAI_BUDGET_PAUSE_FAILURE_RATIO."
        )
    elif report.total_events == 0:
        report.verdict = "quiet"
        report.verdict_reasons.append(
            "no budget mutations in window"
        )
        report.next_action = (
            "Substrate idle. Enable autonomous budget tuning "
            "via data.apply_budget_changes=True in the engine "
            "inputs."
        )
    else:
        report.verdict = "healthy"
        report.verdict_reasons.append(
            f"{report.applied_count} mutation(s) applied "
            f"(cuts={report.cuts_count}, "
            f"pauses={report.pauses_count})"
        )
        report.next_action = (
            f"`shopai marketing-health` to verify failure ratio"
        )
    return report
