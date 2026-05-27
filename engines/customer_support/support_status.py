"""Empire-wide support status (Wave 105).

Customer support autonomy has fanned out across multiple
substrates: refund issuance (Wave 101), refund activity log
(Wave 102), refund auto-pause bridge (Wave 103), customer-
support ticket-tag applier (Wave 104). Operator needed an
empire-wide view that consolidates the lot into a single
verdict: "is the support loop healthy?"

This module aggregates:

  - Refund activity (refund_log) -- counts, $ totals, status
    distribution, per-store
  - Refund health verdict (Wave 103 analyzer)
  - Refund pause state (Wave 103 -- if set, mentioned)
  - Ticket-tag activity (from approval queue rows where
    engine=customer_support AND action_type=apply_ticket_tags)

Verdict band:
  - ``healthy``    -- refund health OK, no pause, activity present
  - ``quiet``      -- no activity in window (substrate idle)
  - ``degraded``   -- refund health degraded OR ticket-tag
                      failures > threshold
  - ``paused``     -- refund auto-pause flag set OR critical
                      verdict from Wave 103
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engines.returns_management.refund_health import (
    analyze_refund_health,
)
from engines.returns_management.refund_state import get_state
from engines.returns_management.refund_status import (
    get_refund_status,
)


@dataclass
class SupportStatusReport:
    window_hours: float
    store_id: str | None = None
    # Refund stack
    refund_total_entries: int = 0
    refund_applied_count: int = 0
    refund_skipped_count: int = 0
    refund_total_amount: float = 0.0
    refund_avg_amount: float = 0.0
    refund_verdict: str = "healthy"
    refund_failure_ratio: float = 0.0
    refund_paused: bool = False
    refund_pause_reason: str = ""
    # Ticket-tag stack
    ticket_tag_total: int = 0
    ticket_tag_applied: int = 0
    ticket_tag_failed: int = 0
    # Aggregate verdict
    verdict: str = "healthy"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def _ticket_tag_activity(
    *,
    window_hours: float,
    store_id: str | None,
) -> tuple[int, int, int]:
    """Count ticket-tag activity from the approval queue.

    Returns ``(total, applied, failed)``. Best-effort: queue
    import failure / API mismatch returns zeros.
    """
    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
        import time as _t
    except Exception:  # noqa: BLE001
        return 0, 0, 0
    cutoff = _t.time() - max(0.0, window_hours) * 3600.0
    queue = None
    try:
        queue = get_approval_queue()
    except Exception:  # noqa: BLE001
        return 0, 0, 0
    if queue is None:
        return 0, 0, 0

    applied = 0
    failed = 0
    for stat, var in (
        (ApprovalStatus.EXECUTED, "applied"),
        (ApprovalStatus.FAILED, "failed"),
    ):
        try:
            rows = queue.list_by_status(
                stat,
                engine="customer_support",
                store_id=store_id,
                limit=500,
            ) or []
        except TypeError:
            # Older queue impl without store_id support
            try:
                rows = queue.list_by_status(
                    stat, engine="customer_support", limit=500,
                ) or []
            except Exception:  # noqa: BLE001
                rows = []
        except Exception:  # noqa: BLE001
            rows = []
        # Filter to ticket-tag action_type + within window
        matching = [
            r for r in rows
            if (
                getattr(r, "action_type", "")
                == "apply_ticket_tags"
                and (
                    getattr(r, "decided_at", 0)
                    or getattr(r, "proposed_at", 0)
                ) >= cutoff
            )
        ]
        if var == "applied":
            applied = len(matching)
        else:
            failed = len(matching)
    return applied + failed, applied, failed


def get_support_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> SupportStatusReport:
    """Build the empire-wide support status report."""
    report = SupportStatusReport(
        window_hours=window_hours,
        store_id=store_id,
    )

    # ── Refund activity (from refund_log) ──────────────────
    refund_act = get_refund_status(
        window_hours=window_hours, store_id=store_id,
    )
    report.refund_total_entries = refund_act.total_entries
    report.refund_applied_count = refund_act.applied_count
    report.refund_skipped_count = refund_act.skipped_count
    report.refund_total_amount = refund_act.total_refunded
    report.refund_avg_amount = refund_act.avg_refund_amount

    # ── Refund health (Wave 103) ───────────────────────────
    # Use the same window as overall report; analyze_refund_
    # health caps below min_sample so this is cheap on empty
    # logs.
    health = analyze_refund_health(window_hours=window_hours)
    report.refund_verdict = health.verdict
    report.refund_failure_ratio = health.failure_ratio

    # ── Refund pause state (Wave 103) ──────────────────────
    pause_state = get_state()
    report.refund_paused = pause_state.paused
    report.refund_pause_reason = pause_state.reason

    # ── Ticket-tag activity (Wave 104 via queue) ───────────
    tt_total, tt_applied, tt_failed = _ticket_tag_activity(
        window_hours=window_hours, store_id=store_id,
    )
    report.ticket_tag_total = tt_total
    report.ticket_tag_applied = tt_applied
    report.ticket_tag_failed = tt_failed

    # ── Aggregate verdict ──────────────────────────────────
    verdict, reasons, next_action = _aggregate_verdict(report)
    report.verdict = verdict
    report.verdict_reasons = reasons
    report.next_action = next_action
    return report


def _aggregate_verdict(
    r: SupportStatusReport,
) -> tuple[str, list[str], str]:
    """Roll up refund + ticket-tag substrate state into one
    verdict + reasons + next_action.

    Order of severity:
      paused > degraded > quiet > healthy
    """
    reasons: list[str] = []

    if r.refund_paused:
        reasons.append(
            f"refund auto-pause active: "
            f"{r.refund_pause_reason or '(no reason)'}"
        )
        return (
            "paused",
            reasons,
            "Resume via `shopai refund-resume` once the "
            "underlying issue is addressed.",
        )

    if r.refund_verdict == "critical":
        reasons.append(
            f"refund failure ratio "
            f"{r.refund_failure_ratio:.0%} >= critical "
            "threshold"
        )
        return (
            "degraded",
            reasons,
            "Run `shopai refund-health --apply-bridge` to "
            "auto-pause; investigate adapter_failed rows.",
        )

    if r.refund_verdict == "degraded":
        reasons.append(
            f"refund failure ratio "
            f"{r.refund_failure_ratio:.0%} above warn "
            "threshold"
        )

    # Ticket-tag failure ratio above 30% is degraded
    if r.ticket_tag_total >= 5:
        fail_ratio = r.ticket_tag_failed / r.ticket_tag_total
        if fail_ratio >= 0.30:
            reasons.append(
                f"ticket-tag failure ratio "
                f"{fail_ratio:.0%} above 30%"
            )
            return (
                "degraded",
                reasons,
                "Check the SHOPIFY_TAG_CUSTOMER adapter "
                "scope + connectivity.",
            )

    # Quiet vs healthy
    total_activity = (
        r.refund_total_entries + r.ticket_tag_total
    )
    if total_activity == 0:
        reasons.append(
            "no refund or ticket-tag activity in window"
        )
        return (
            "quiet",
            reasons,
            "Substrate is idle. Enable autonomous flows "
            "via data.apply_refunds=True / "
            "data.apply_ticket_tags=True in the engine "
            "inputs.",
        )

    if r.refund_verdict == "degraded":
        # Degraded but not critical -- surface but don't pause
        return (
            "degraded",
            reasons,
            "Monitor closely; consider lowering "
            "SHOPAI_REFUND_PAUSE_FAILURE_RATIO if pattern "
            "persists.",
        )

    reasons.append(
        f"{r.refund_applied_count} refunds applied "
        f"(${r.refund_total_amount:,.2f}), "
        f"{r.ticket_tag_applied} ticket-tag updates"
    )
    return (
        "healthy",
        reasons,
        f"`shopai refund-status --window-hours "
        f"{int(r.window_hours)}` to drill into refunds.",
    )
