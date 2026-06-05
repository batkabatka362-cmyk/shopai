"""Compose day-end signal into one evening brief."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EveningBrief:
    store_id: str
    window_hours: float = 24.0
    cycle_runs_today: int = 0
    cycle_success_runs: int = 0
    cycle_failed_runs: int = 0
    actions_executed_today: int = 0
    actions_rejected_today: int = 0
    outcomes_recorded_today: int = 0
    current_verdict: str = "no_data"
    current_gross_profit: float = 0.0
    current_attribution_pct: float = 0.0
    previous_verdict: str = "no_data"
    verdict_changed: bool = False
    history_trend: str = "no_data"
    headline: str = ""
    next_action: str = ""


def _gather_cycle_history(b: EveningBrief) -> None:
    try:
        from engines._cycle_history import recent_runs
        cutoff = time.time() - (b.window_hours * 3600.0)
        runs = recent_runs(limit=50) or []
        for r in runs:
            ts = float(getattr(r, "started_at", 0) or 0)
            if ts < cutoff:
                continue
            b.cycle_runs_today += 1
            verdict = str(getattr(r, "verdict", ""))
            if verdict in ("clean", "mostly_ok"):
                b.cycle_success_runs += 1
            elif verdict in ("failed", "degraded"):
                b.cycle_failed_runs += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("evening: cycle raised: %s", exc)


def _gather_queue_activity(b: EveningBrief) -> None:
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        cutoff = time.time() - (b.window_hours * 3600.0)
        for status, attr in (
            ("executed", "actions_executed_today"),
            ("rejected", "actions_rejected_today"),
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
            setattr(b, attr, count)
    except Exception as exc:  # noqa: BLE001
        logger.debug("evening: queue raised: %s", exc)


def _gather_outcomes(b: EveningBrief) -> None:
    """Count outcomes recorded in the last window via the
    approval queue's outcome events."""
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        cutoff = time.time() - (b.window_hours * 3600.0)
        # Walk executed/rejected actions and their outcomes
        count = 0
        for status in ("executed", "rejected"):
            try:
                rows = q.list_by_status(status) or []
            except Exception:  # noqa: BLE001
                continue
            for row in rows:
                aid = getattr(row, "id", "")
                if not aid:
                    continue
                try:
                    outs = q.get_outcomes(aid) or []
                except Exception:  # noqa: BLE001
                    continue
                for o in outs:
                    ts = (
                        o.get("recorded_at")
                        if isinstance(o, dict) else None
                    )
                    try:
                        if (
                            ts is None
                            or float(ts) < cutoff
                        ):
                            continue
                    except (TypeError, ValueError):
                        continue
                    count += 1
        b.outcomes_recorded_today = count
    except Exception as exc:  # noqa: BLE001
        logger.debug("evening: outcomes raised: %s", exc)


def _gather_current_and_previous(
    b: EveningBrief,
) -> None:
    try:
        from engines.agi_earnings_summary.summarizer import (
            compute_summary,
        )
        s = compute_summary(days=7)
        b.current_verdict = s.verdict
        b.current_gross_profit = s.fleet_gross_profit
        b.current_attribution_pct = s.fleet_attribution_pct
    except Exception as exc:  # noqa: BLE001
        logger.debug("evening: current raised: %s", exc)
    try:
        from engines.agi_earnings_history import store as h
        snaps = h.query(days=2, limit=10)
        # Newest-first. Skip 0 (today's record if exists),
        # pick the first one from before the window.
        cutoff = time.time() - (b.window_hours * 3600.0)
        for snap in snaps:
            ts = float(snap.get("ts", 0) or 0)
            if ts < cutoff:
                b.previous_verdict = str(
                    snap.get("verdict") or "no_data",
                )
                break
        t = h.compute_trend(days=7)
        b.history_trend = str(
            t.get("verdict", "no_data"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("evening: history raised: %s", exc)
    b.verdict_changed = (
        b.previous_verdict != "no_data"
        and b.previous_verdict != b.current_verdict
    )


def _build_headline(b: EveningBrief) -> str:
    if b.cycle_runs_today == 0:
        return (
            f"Quiet day: no cycles ran in the last "
            f"{b.window_hours:.0f}h."
        )
    base = (
        f"{b.cycle_runs_today} cycle(s) ran; "
        f"{b.actions_executed_today} action(s) "
        f"executed; verdict={b.current_verdict}"
    )
    if b.verdict_changed:
        return (
            f"VERDICT CHANGED: {b.previous_verdict} -> "
            f"{b.current_verdict}. {base}."
        )
    return base + "."


def _build_next_action(b: EveningBrief) -> str:
    if b.cycle_failed_runs > 0:
        return (
            f"{b.cycle_failed_runs} cycle(s) failed -- "
            "run shopai engine alerts before bed."
        )
    if (
        b.cycle_runs_today > 0
        and b.actions_executed_today == 0
    ):
        return (
            "Cycles ran but 0 actions executed -- check "
            "shopai approvals digest."
        )
    if b.verdict_changed:
        return (
            f"Verdict shifted to {b.current_verdict}; "
            "review shopai morning-brief in the AM."
        )
    if b.cycle_runs_today == 0:
        return (
            "No cycles today. Schedule via "
            "shopai cycle schedule."
        )
    return (
        "Clean day -- shopai morning-brief --record "
        "to snapshot trend."
    )


def build_evening_brief(
    *,
    store_id: str = "",
    window_hours: float = 24.0,
) -> EveningBrief:
    b = EveningBrief(
        store_id=store_id,
        window_hours=max(1.0, float(window_hours)),
    )
    _gather_cycle_history(b)
    _gather_queue_activity(b)
    _gather_outcomes(b)
    _gather_current_and_previous(b)
    b.headline = _build_headline(b)
    b.next_action = _build_next_action(b)
    return b
