"""Recommend an optimal cron interval from observed signal."""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CronRecommendation:
    interval_hours: float = 2.0
    reason: str = ""
    cron_line: str = ""
    windows_task: str = ""
    confidence: str = "low"   # low / medium / high
    signals: dict[str, Any] = field(default_factory=dict)


_CRON_INTERVALS = {
    1.0: "0 * * * *",
    2.0: "0 */2 * * *",
    4.0: "0 */4 * * *",
    24.0: "0 6 * * *",
}


def _windows_template(interval_hours: float) -> str:
    if interval_hours <= 1.0:
        return (
            'schtasks /Create /SC HOURLY /TN "ShopAICycle" '
            '/TR "shopai cycle run --yes"'
        )
    if interval_hours <= 24.0:
        return (
            f'schtasks /Create /SC HOURLY /MO '
            f'{int(interval_hours)} /TN "ShopAICycle" '
            '/TR "shopai cycle run --yes"'
        )
    return (
        'schtasks /Create /SC DAILY /TN "ShopAICycle" '
        '/TR "shopai cycle run --yes"'
    )


def _gather_cycle_signals(s: dict[str, Any]) -> None:
    try:
        from engines._cycle_history import recent_runs
        cutoff = time.time() - 7 * 86400.0
        runs = recent_runs(limit=200) or []
        n = ok = failed = 0
        for r in runs:
            ts = float(getattr(r, "started_at", 0) or 0)
            if ts < cutoff:
                continue
            n += 1
            v = str(getattr(r, "verdict", ""))
            if v in ("clean", "mostly_ok"):
                ok += 1
            elif v in ("failed", "degraded"):
                failed += 1
        s["cycles_7d"] = n
        s["cycles_failed_7d"] = failed
        s["cycles_failure_rate"] = (
            round(failed / n, 3) if n else 0.0
        )
        # Per-day average
        s["cycles_per_day"] = round(n / 7.0, 1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cron: cycle raised: %s", exc)


def _gather_action_velocity(s: dict[str, Any]) -> None:
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        cutoff = time.time() - 7 * 86400.0
        executed = 0
        for row in q.list_by_status("executed") or []:
            ts = getattr(row, "decided_at", None)
            try:
                if ts is None or float(ts) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            executed += 1
        s["actions_executed_7d"] = executed
        cycles = s.get("cycles_7d", 0) or 0
        s["actions_per_cycle"] = (
            round(executed / cycles, 2)
            if cycles else 0.0
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("cron: queue raised: %s", exc)


def _gather_verdict_drift(s: dict[str, Any]) -> None:
    try:
        from engines.agi_earnings_history import store as h
        snaps = h.query(days=2, limit=50)
        transitions = 0
        last = None
        for snap in reversed(snaps):
            v = str(snap.get("verdict") or "no_data")
            if last is not None and v != last:
                transitions += 1
            last = v
        s["verdict_transitions_2d"] = transitions
        s["verdict_drift_per_day"] = round(
            transitions / 2.0, 2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("cron: drift raised: %s", exc)


def _gather_anomaly_signal(s: dict[str, Any]) -> None:
    try:
        from engines.agi_anomaly_detector.detector import (
            detect,
        )
        r = detect(window=14)
        s["anomaly_count"] = len(r.anomalies)
        s["critical_anomaly_count"] = sum(
            1 for a in r.anomalies
            if a.severity == "critical"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("cron: anomaly raised: %s", exc)


def _decide(s: dict[str, Any]) -> tuple[
    float, str, str,
]:
    """Returns (interval_hours, reason, confidence)."""
    cycles = int(s.get("cycles_7d", 0) or 0)
    cycles_per_day = float(s.get("cycles_per_day", 0) or 0)
    failure_rate = float(
        s.get("cycles_failure_rate", 0) or 0,
    )
    actions_per_cycle = float(
        s.get("actions_per_cycle", 0) or 0,
    )
    drift = float(s.get("verdict_drift_per_day", 0) or 0)
    crit_anom = int(
        s.get("critical_anomaly_count", 0) or 0,
    )
    if cycles == 0:
        return (
            1.0,
            "Empty empire -- hourly kick-start.",
            "low",
        )
    if crit_anom > 0:
        return (
            1.0,
            (
                f"{crit_anom} critical anomaly(ies) -- "
                "hourly to close detection gap."
            ),
            "high",
        )
    if failure_rate >= 0.25:
        return (
            2.0,
            (
                f"{failure_rate:.0%} failure rate -- "
                "2h prevents fast-loop debt accumulation."
            ),
            "medium",
        )
    if drift >= 2.0:
        return (
            1.0,
            (
                f"Verdict shifting {drift:.1f}/day -- "
                "hourly keeps signal fresh."
            ),
            "medium",
        )
    if (
        cycles_per_day >= 4.0
        and actions_per_cycle < 0.5
    ):
        return (
            4.0,
            (
                f"{cycles_per_day:.1f} cycles/day producing "
                f"only {actions_per_cycle:.2f} actions each "
                "-- 4h reduces waste."
            ),
            "high",
        )
    if drift <= 0.2 and actions_per_cycle < 1.0:
        return (
            24.0,
            (
                "Very low activity (drift+actions both "
                "near zero) -- daily is enough."
            ),
            "medium",
        )
    return (
        2.0,
        "Steady-state -- 2h balanced default.",
        "medium",
    )


def recommend(
    *,
    signals_override: dict[str, Any] | None = None,
) -> CronRecommendation:
    rec = CronRecommendation()
    if signals_override is not None:
        signals = dict(signals_override)
    else:
        signals = {}
        _gather_cycle_signals(signals)
        _gather_action_velocity(signals)
        _gather_verdict_drift(signals)
        _gather_anomaly_signal(signals)
    rec.signals = signals
    rec.interval_hours, rec.reason, rec.confidence = _decide(
        signals,
    )
    cron = _CRON_INTERVALS.get(rec.interval_hours)
    if cron is None:
        cron = f"0 */{int(rec.interval_hours)} * * *"
    rec.cron_line = (
        f"{cron} shopai cycle run --yes "
        ">> /var/log/shopai-cycle.log 2>&1"
    )
    rec.windows_task = _windows_template(rec.interval_hours)
    return rec


def platform_template(rec: CronRecommendation) -> str:
    """Pick the right template for current platform."""
    if sys.platform == "win32":
        return rec.windows_task
    return rec.cron_line
