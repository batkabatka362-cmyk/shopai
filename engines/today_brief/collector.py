"""Collect the 5 signals that drive the today brief.

Each collector is best-effort: substrate that isn't wired
returns a "skipped" verdict so the brief still renders.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TodaySignal:
    name: str
    verdict: str  # ok / warn / critical / skipped
    headline: str
    detail: str = ""
    drill: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _today_day_signal(
    day: int, niche: str | None,
) -> TodaySignal:
    """Pull the warmup-plan day-of action."""
    try:
        from engines.warmup_plan.schedule import get_day
        wd = get_day(day, niche=niche)
        if wd is None:
            return TodaySignal(
                name="warmup_plan",
                verdict="skipped",
                headline=f"Day {day} is beyond 30-day plan",
                drill=(
                    "shopai cycle schedule -- recurring "
                    "cycle mode"
                ),
            )
        first_action = (
            wd.actions[0] if wd.actions else ""
        )
        return TodaySignal(
            name="warmup_plan",
            verdict="ok",
            headline=(
                f"Day {wd.day} [{wd.phase}]: {wd.intent}"
            ),
            detail=first_action,
            drill=(
                f"shopai warmup-plan --day {wd.day} "
                f"--niche {niche or 'general'}"
            ),
            data={"day": wd.day, "phase": wd.phase},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("warmup_plan collector raised: %s", exc)
        return TodaySignal(
            name="warmup_plan",
            verdict="skipped",
            headline="Warmup-plan substrate unavailable",
        )


def _readiness_signal(
    store_id: str | None,
) -> TodaySignal:
    """Snapshot revenue_readiness verdict."""
    try:
        from engines.revenue_readiness import (
            RevenueReadinessEngine,
        )
        payload = {"data": {}}
        if store_id:
            payload["data"]["store_id"] = store_id
        result = RevenueReadinessEngine().run(payload)
        data = result.get("data") or {}
        verdict_str = data.get("verdict") or "unknown"
        passed = data.get("gates_passed") or 0
        total = data.get("gates_total") or 0
        v = {
            "earning_active": "ok",
            "growing": "ok",
            "launching": "warn",
            "cold_start": "warn",
            "unknown": "skipped",
        }.get(verdict_str, "warn")
        if total and passed < (total / 2):
            v = "critical"
        return TodaySignal(
            name="readiness",
            verdict=v,
            headline=(
                f"Readiness verdict: {verdict_str} "
                f"({passed}/{total} gates)"
            ),
            detail=data.get("next_action", "") or "",
            drill="shopai diagnose [--store STORE]",
            data={
                "verdict": verdict_str,
                "gates_passed": passed,
                "gates_total": total,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("readiness collector raised: %s", exc)
        return TodaySignal(
            name="readiness",
            verdict="skipped",
            headline="Readiness substrate unavailable",
        )


def _autonomy_signal(
    store_id: str | None,
) -> TodaySignal:
    """Aggregate per-domain autonomy verdicts."""
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        kwargs = {}
        if store_id:
            kwargs["store_id"] = store_id
        report = get_autonomy_status(**kwargs)
        overall = getattr(report, "overall_verdict", "")
        paused = [
            d.name for d in getattr(report, "domains", []) or []
            if getattr(d, "paused", False)
        ]
        bad_count = len(paused)
        v = {
            "paused": "critical",
            "degraded": "warn",
            "quiet": "ok",
            "healthy": "ok",
        }.get(overall, "skipped")
        headline = f"Autonomy: {overall or 'unknown'}"
        if paused:
            headline += f" ({bad_count} paused)"
        return TodaySignal(
            name="autonomy",
            verdict=v,
            headline=headline,
            detail=(
                f"paused={','.join(paused)}"
                if paused
                else "all domains operational"
            ),
            drill="shopai autonomy-status [--store STORE]",
            data={
                "overall": overall,
                "paused_domains": paused,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("autonomy collector raised: %s", exc)
        return TodaySignal(
            name="autonomy",
            verdict="skipped",
            headline="Autonomy substrate unavailable",
        )


def _approval_signal(
    store_id: str | None,
) -> TodaySignal:
    """Pull head of approval queue."""
    try:
        from core.approval import ApprovalQueue
        q = ApprovalQueue()
        kwargs = {"limit": 5}
        if store_id:
            kwargs["store_id"] = store_id
        pending = list(q.list_pending(**kwargs))
        n = len(pending)
        if n == 0:
            return TodaySignal(
                name="approvals",
                verdict="ok",
                headline="Approval queue: empty",
                drill="shopai approvals pending",
            )
        verdict = "warn" if n >= 5 else "ok"
        sample = pending[0]
        eng = (
            getattr(sample, "engine", "?")
            if not isinstance(sample, dict)
            else sample.get("engine", "?")
        )
        return TodaySignal(
            name="approvals",
            verdict=verdict,
            headline=f"Approval queue: {n} pending",
            detail=f"top: {eng}",
            drill="shopai approvals digest",
            data={"pending_count": n, "top_engine": eng},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval collector raised: %s", exc)
        return TodaySignal(
            name="approvals",
            verdict="skipped",
            headline="Approval substrate unavailable",
        )


def _cycle_signal() -> TodaySignal:
    """Pull last-cycle status."""
    try:
        from engines._cycle_history import last_run
        lr = last_run()
        if lr is None:
            return TodaySignal(
                name="cycle",
                verdict="warn",
                headline="No cycle has run yet",
                drill=(
                    "shopai cycle run --yes -- first cycle"
                ),
            )
        ok = bool(getattr(lr, "ok", True))
        when = getattr(lr, "run_id", "?")
        v = "ok" if ok else "warn"
        return TodaySignal(
            name="cycle",
            verdict=v,
            headline=(
                f"Last cycle: "
                f"{'ok' if ok else 'errors'} ({when})"
            ),
            drill="shopai cycle status",
            data={"ok": ok, "run_id": when},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("cycle collector raised: %s", exc)
        return TodaySignal(
            name="cycle",
            verdict="skipped",
            headline="Cycle substrate unavailable",
        )


def collect_today_signals(
    *,
    day: int,
    niche: str | None,
    store_id: str | None,
) -> list[TodaySignal]:
    """Return the 5 signals in display order."""
    return [
        _today_day_signal(day, niche),
        _readiness_signal(store_id),
        _autonomy_signal(store_id),
        _cycle_signal(),
        _approval_signal(store_id),
    ]


def overall_verdict(signals: list[TodaySignal]) -> str:
    """Return overall verdict: critical > warn > ok > skipped."""
    sev = {
        "critical": 0, "warn": 1, "ok": 2, "skipped": 3,
    }
    worst = "skipped"
    for s in signals:
        if sev.get(s.verdict, 3) < sev.get(worst, 3):
            worst = s.verdict
    return worst


def first_critical_action(signals: list[TodaySignal]) -> str:
    """Return the drill hint for the highest-severity signal,
    or the warmup-plan drill if all are clean."""
    for sev in ("critical", "warn"):
        for s in signals:
            if s.verdict == sev and s.drill:
                return s.drill
    # No urgent issues -> point at warmup-plan day-of.
    for s in signals:
        if s.name == "warmup_plan" and s.drill:
            return s.drill
    return ""
