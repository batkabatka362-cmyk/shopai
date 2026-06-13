"""Wave 100: post-onboarding status surface.

After ``shopai onboard`` finishes, the operator wants to know:
did the autonomous cycle actually start running for this store?
Has revenue come in? Are there outstanding launch gaps?

``shopai world-model show <store>`` answers a generic snapshot
question; ``shopai daily-brief`` is empire-wide. Wave 100 ships
a focused view tied to the LAUNCH-TO-EARNING journey:

  - When was the store onboarded?
  - How many cycles have fired since then?
  - What's the engine activity in the post-onboarding window?
  - Are there outstanding launch gaps to close?
  - Has any revenue been attributed?

Output verdict: ``thriving`` / ``quiet`` / ``needs_attention``
based on cycle cadence + engine activity + open gaps.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OnboardStatus:
    store_id: str
    found: bool = True
    error: str = ""

    onboarded_at: float | None = None
    onboarded_age_hours: float | None = None

    # Cycle activity
    cycles_since_onboarding: int = 0
    last_cycle_age_hours: float | None = None
    last_cycle_verdict: str = ""

    # Engine activity (post-onboarding window)
    activity_executed: int = 0
    activity_failed: int = 0
    activity_pending: int = 0

    # Launch readiness (re-audit on demand)
    launch_gaps_total: int = 0
    launch_gaps_manual: int = 0
    launch_gaps_closeable: int = 0

    # Revenue (since onboarding window)
    attributed_revenue: float = 0.0
    attributed_orders: int = 0

    # Niche state
    niche: str = ""
    niche_active: bool = False

    verdict: str = "unknown"
    verdict_reasons: list[str] = field(default_factory=list)
    next_action: str = ""


def _now() -> float:
    return time.time()


def get_onboard_status(
    store_id: str,
    *,
    store_manager: Any = None,
    include_audit: bool = False,
) -> OnboardStatus:
    """Compute post-onboarding status for one store.

    Args:
        store_id: Stable store identifier.
        store_manager: Optional StoreManager override (tests).
        include_audit: When True, runs launch_audit.audit_store
            to populate launch_gaps_*. OFF by default because
            the audit hits Shopify for every check; operator
            opts in via CLI flag.

    Returns:
        Populated :class:`OnboardStatus`.
    """
    status = OnboardStatus(store_id=store_id)

    sm = store_manager
    if sm is None:
        try:
            from data_pipeline.store.store_manager import (
                StoreManager,
            )
            sm = StoreManager()
        except Exception as exc:  # noqa: BLE001
            status.found = False
            status.error = f"StoreManager unavailable: {exc}"
            return status

    try:
        row = sm.get_store(store_id)
    except Exception as exc:  # noqa: BLE001
        status.found = False
        status.error = f"get_store raised: {exc}"
        return status
    if not row:
        status.found = False
        status.error = f"store '{store_id}' not found"
        return status

    # ── Onboarding age ─────────────────────────────────────
    created = row.get("created_at")
    if isinstance(created, (int, float)) and created > 0:
        status.onboarded_at = float(created)
        status.onboarded_age_hours = (
            (_now() - float(created)) / 3600.0
        )
    status.niche = (row.get("niche") or "").strip().lower()
    status.niche_active = (
        bool(status.niche)
        and status.niche != "general"
    )

    cutoff = status.onboarded_at or 0.0

    # ── Cycles since onboarding ────────────────────────────
    try:
        from engines._cycle_history import recent_runs
        runs = recent_runs(limit=200) or []
        post_onboard = [
            r for r in runs
            if r.started_at >= cutoff
        ]
        status.cycles_since_onboarding = len(post_onboard)
        if post_onboard:
            # recent_runs is desc by started_at
            latest = post_onboard[0]
            status.last_cycle_age_hours = (
                (_now() - latest.started_at) / 3600.0
            )
            status.last_cycle_verdict = (
                getattr(latest, "verdict", "") or ""
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "onboard-status cycle history raised: %s", exc,
        )

    # ── Engine activity in window ──────────────────────────
    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
        queue = get_approval_queue()
        # Executed + failed in the window
        for stat, attr in (
            (ApprovalStatus.EXECUTED, "activity_executed"),
            (ApprovalStatus.FAILED,   "activity_failed"),
        ):
            try:
                rows = queue.list_by_status(
                    stat, store_id=store_id, limit=500,
                ) or []
            except TypeError:
                # Pre-PR239 queues without store_id filter
                rows = []
            count = sum(
                1 for a in rows
                if (a.decided_at or a.proposed_at or 0)
                >= cutoff
            )
            setattr(status, attr, count)
        # Pending (current state, not historical)
        try:
            pend = queue.list_by_status(
                ApprovalStatus.PENDING,
                store_id=store_id, limit=500,
            ) or []
        except TypeError:
            pend = []
        status.activity_pending = len(pend)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "onboard-status approval queue raised: %s", exc,
        )

    # ── Launch audit gaps (opt-in) ─────────────────────────
    if include_audit:
        try:
            from engines.store_setup.launch_audit import (
                audit_store,
            )
            audit = audit_store(store_id=store_id)
            manual = audit.get("manual_admin_gaps") or []
            closeable = audit.get("launch_closeable_gaps") or []
            status.launch_gaps_manual = len(manual)
            status.launch_gaps_closeable = len(closeable)
            status.launch_gaps_total = (
                status.launch_gaps_manual
                + status.launch_gaps_closeable
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "onboard-status audit raised: %s", exc,
            )

    # ── Revenue attribution (since-onboarding window) ──────
    try:
        from engines._revenue_attribution import (
            attribute_revenue,
        )
        # Convert age-hours-since-onboarding into window hours
        window_h = (
            status.onboarded_age_hours
            if status.onboarded_age_hours is not None
            else 168.0
        )
        report = attribute_revenue(
            window_hours=window_h, store_id=store_id,
        )
        status.attributed_revenue = float(
            sum(
                c.attributed_revenue for c in report.per_cluster
            )
        )
        status.attributed_orders = sum(
            c.attributed_orders for c in report.per_cluster
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "onboard-status attribution raised: %s", exc,
        )

    # ── Verdict ────────────────────────────────────────────
    status.verdict, status.verdict_reasons = _verdict(status)
    status.next_action = _next_action(status)
    return status


def _verdict(s: OnboardStatus) -> tuple[str, list[str]]:
    """Classify the store's post-onboarding state.

    Bands:
      - ``thriving``: cycles firing + activity > 0 + no gaps
      - ``quiet``:    no activity OR no recent cycles
      - ``needs_attention``: stale (cycles >48h) OR many failures
                              OR open launch gaps + 0 closure
    """
    reasons: list[str] = []
    # If the store wasn't onboarded long enough to expect
    # activity, default to "quiet" rather than "needs_attention".
    age_h = s.onboarded_age_hours or 0.0
    if age_h < 1.0:
        return "just_onboarded", [
            f"only {age_h*60:.0f} min since register"
        ]

    last_h = s.last_cycle_age_hours
    if last_h is None:
        reasons.append("no cycles have run for this store yet")
        if age_h > 24:
            reasons.append(
                "onboarded >24h ago but cron has not fired"
            )
            return "needs_attention", reasons
        return "quiet", reasons
    if last_h > 48:
        reasons.append(
            f"last cycle ran {last_h:.0f}h ago (>48h stale)"
        )
        return "needs_attention", reasons
    # Failed-heavy: more failures than success
    if (
        s.activity_failed > s.activity_executed
        and s.activity_failed >= 3
    ):
        reasons.append(
            f"{s.activity_failed} failed vs "
            f"{s.activity_executed} executed"
        )
        return "needs_attention", reasons
    # Audit gaps with no closure activity
    if s.launch_gaps_total > 0:
        if s.launch_gaps_closeable > 0:
            reasons.append(
                f"{s.launch_gaps_closeable} auto-closeable gap(s)"
            )
            return "needs_attention", reasons
        if s.launch_gaps_manual > 0:
            reasons.append(
                f"{s.launch_gaps_manual} operator-only gap(s)"
            )
            return "quiet", reasons
    # All positive
    if s.activity_executed > 0:
        reasons.append(
            f"{s.activity_executed} action(s) executed; "
            f"{s.cycles_since_onboarding} cycle(s) since onboarding"
        )
        return "thriving", reasons
    reasons.append(
        f"{s.cycles_since_onboarding} cycle(s) ran but no "
        "engine activity yet"
    )
    return "quiet", reasons


def _next_action(s: OnboardStatus) -> str:
    """Operator hint based on verdict."""
    if s.verdict == "needs_attention":
        if s.last_cycle_age_hours is None and (
            s.onboarded_age_hours or 0
        ) > 24:
            return (
                "install the cron line: "
                "`shopai cycle schedule`"
            )
        if s.launch_gaps_closeable > 0:
            return (
                f"re-run `shopai launch --store-id "
                f"{s.store_id}` to close auto-closeable gaps"
            )
        if s.activity_failed >= 3:
            return (
                f"`shopai engine alerts --store {s.store_id}` "
                "to triage failures"
            )
        return (
            f"`shopai world-model show {s.store_id}` "
            "to drill in"
        )
    if s.verdict == "quiet":
        if s.launch_gaps_manual > 0:
            return (
                "close manual-admin gaps in Shopify admin "
                "(see `shopai launch-audit --store-id "
                f"{s.store_id}`)"
            )
        return (
            f"wait for cron to fire + re-check via "
            f"`shopai onboard-status {s.store_id}`"
        )
    if s.verdict == "thriving":
        return (
            f"monitor via `shopai daily-brief` or drill "
            f"with `shopai world-model show {s.store_id}`"
        )
    if s.verdict == "just_onboarded":
        return (
            "wait for first cycle to fire (or run "
            "`shopai cycle run --yes` for a one-shot smoke)"
        )
    return ""
