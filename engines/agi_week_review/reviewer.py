"""Compose 7-day signal into one weekly review."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Verdict ladder (higher = healthier). attributed_loss is
# BELOW organic_only because the empire is actively losing
# under AGI control vs merely failing to attribute -- the
# former is strictly worse.
_VERDICT_RANK = {
    "no_data":         0,
    "attributed_loss": 1,
    "organic_only":    2,
    "earning":         3,
}


@dataclass
class WeekReview:
    store_id: str
    days: int = 7
    cycle_total: int = 0
    cycle_success_rate: float = 0.0
    actions_executed: int = 0
    actions_rejected: int = 0
    rejection_rate: float = 0.0
    snapshot_count: int = 0
    verdict_timeline: list[dict[str, Any]] = field(
        default_factory=list,
    )
    verdict_transitions: int = 0
    distinct_verdicts: list[str] = field(
        default_factory=list,
    )
    fleet_attribution_pct: float = 0.0
    fleet_orphan_action_count: int = 0
    week_verdict: str = "quiet"
    headline: str = ""
    next_action: str = ""


def _gather_cycle_stats(r: WeekReview) -> None:
    try:
        from engines._cycle_history import recent_runs
        cutoff = time.time() - (r.days * 86400.0)
        runs = recent_runs(limit=200) or []
        ok_n = total_decided = 0
        for run in runs:
            ts = float(
                getattr(run, "started_at", 0) or 0,
            )
            if ts < cutoff:
                continue
            r.cycle_total += 1
            verdict = str(getattr(run, "verdict", ""))
            if verdict == "dry_run":
                continue
            total_decided += 1
            if verdict in ("clean", "mostly_ok"):
                ok_n += 1
        if total_decided > 0:
            r.cycle_success_rate = round(
                ok_n / total_decided, 3,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("week: cycle raised: %s", exc)


def _gather_queue_stats(r: WeekReview) -> None:
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        cutoff = time.time() - (r.days * 86400.0)
        for status, attr in (
            ("executed", "actions_executed"),
            ("rejected", "actions_rejected"),
        ):
            try:
                rows = q.list_by_status(status) or []
            except Exception:  # noqa: BLE001
                continue
            count = 0
            for row in rows:
                ts = getattr(row, "decided_at", None)
                try:
                    if ts is None or float(ts) < cutoff:
                        continue
                except (TypeError, ValueError):
                    continue
                count += 1
            setattr(r, attr, count)
        decided = r.actions_executed + r.actions_rejected
        if decided > 0:
            r.rejection_rate = round(
                r.actions_rejected / decided, 3,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("week: queue raised: %s", exc)


def _gather_verdict_timeline(r: WeekReview) -> None:
    try:
        from engines.agi_earnings_history import store as h
        snaps = h.query(days=r.days, limit=500)
        # query returns newest-first; flip to oldest-first
        # for the timeline
        snaps = list(reversed(snaps))
        r.snapshot_count = len(snaps)
        last_v: str | None = None
        seen: list[str] = []
        for s in snaps:
            v = str(s.get("verdict") or "no_data")
            ts = float(s.get("ts", 0) or 0)
            r.verdict_timeline.append({
                "ts": ts,
                "verdict": v,
                "gross_profit": s.get("gross_profit", 0.0),
            })
            if last_v is not None and v != last_v:
                r.verdict_transitions += 1
            last_v = v
            if v not in seen:
                seen.append(v)
        r.distinct_verdicts = seen
    except Exception as exc:  # noqa: BLE001
        logger.debug("week: timeline raised: %s", exc)


def _gather_reconciliation(r: WeekReview) -> None:
    try:
        from engines.revenue_reconciliation.reconciler import (
            reconcile_fleet,
        )
        rc = reconcile_fleet(days=r.days)
        r.fleet_attribution_pct = rc.fleet_attribution_pct
        r.fleet_orphan_action_count = (
            rc.fleet_orphan_action_count
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("week: recon raised: %s", exc)


def _classify_week_verdict(r: WeekReview) -> str:
    """Look at the verdict timeline + count of cycles to
    decide the macro-week verdict."""
    if r.cycle_total == 0 and r.snapshot_count == 0:
        return "quiet"
    if not r.verdict_timeline:
        if r.cycle_total > 0:
            return "running_blind"
        return "quiet"
    # Rank trajectory: first vs last
    first = r.verdict_timeline[0]["verdict"]
    last = r.verdict_timeline[-1]["verdict"]
    first_rank = _VERDICT_RANK.get(first, 0)
    last_rank = _VERDICT_RANK.get(last, 0)
    delta = last_rank - first_rank
    if delta >= 2:
        return "growing"
    if delta == 1:
        return "recovering"
    if delta <= -2:
        return "regressing"
    if delta == -1:
        return "softening"
    # Stable
    if last == "earning":
        return "stable_earning"
    if last == "organic_only":
        return "stable_organic"
    if last == "attributed_loss":
        return "stable_loss"
    return "quiet"


def _build_headline(r: WeekReview) -> str:
    v = r.week_verdict
    base = (
        f"{r.cycle_total} cycle(s), "
        f"{r.actions_executed} action(s), "
        f"{r.verdict_transitions} verdict transition(s)"
    )
    head = {
        "growing":        f"GROWING -- {base}.",
        "recovering":     f"RECOVERING -- {base}.",
        "regressing":     f"REGRESSING -- {base}.",
        "softening":      f"SOFTENING -- {base}.",
        "stable_earning": f"STABLE EARNING -- {base}.",
        "stable_organic": f"STABLE ORGANIC -- {base}.",
        "stable_loss":    f"STABLE LOSS -- {base}.",
        "running_blind":  (
            f"RUNNING BLIND -- cycles fired but no "
            f"verdict snapshots ({r.cycle_total} cycles)."
        ),
        "quiet":          (
            f"QUIET WEEK -- {r.cycle_total} cycle(s); "
            "consider arming substrate."
        ),
    }
    return head.get(v, base)


def _build_next_action(r: WeekReview) -> str:
    v = r.week_verdict
    if v == "regressing":
        return (
            "Regression -- shopai engine alerts "
            "then shopai action-critic."
        )
    if v == "growing":
        return (
            "Compound the wins -- "
            "shopai transfer scan."
        )
    if v == "running_blind":
        return (
            "Schedule daily snapshot: shopai "
            "morning-brief --record (or cron)."
        )
    if v == "stable_loss":
        return (
            "Persistent loss -- shopai roas "
            "to find the bleeders."
        )
    if v == "stable_organic":
        return (
            "0% AGI attribution all week -- "
            "shopai engine ranking."
        )
    if v == "quiet":
        return (
            "Empire idle. Run shopai cycle run "
            "--yes or schedule cycles."
        )
    if v == "recovering":
        return (
            "Recovery -- shopai morning-brief "
            "to keep the trajectory."
        )
    if v == "softening":
        return (
            "Trend softening -- shopai action-critic "
            "to stress-test next moves."
        )
    return (
        "Stable earning -- compound via "
        "shopai approvals batch-review."
    )


def build_week_review(
    *,
    store_id: str = "",
    days: int = 7,
) -> WeekReview:
    r = WeekReview(
        store_id=store_id,
        days=max(2, min(days, 90)),
    )
    _gather_cycle_stats(r)
    _gather_queue_stats(r)
    _gather_verdict_timeline(r)
    _gather_reconciliation(r)
    r.week_verdict = _classify_week_verdict(r)
    r.headline = _build_headline(r)
    r.next_action = _build_next_action(r)
    return r
