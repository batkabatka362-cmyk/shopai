"""Count consecutive un-acted-upon recommendation streaks."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_STRESS_VERDICTS = frozenset({
    "attributed_loss",
    "organic_only",
})


@dataclass
class Streak:
    name: str
    count: int = 0
    severity: str = "info"
    drill: str = ""
    detail: str = ""


@dataclass
class StreakReport:
    samples_scanned: int = 0
    loss_streak: Streak = field(default_factory=lambda: Streak(
        name="loss_streak",
    ))
    no_data_streak: Streak = field(default_factory=lambda: Streak(
        name="no_data_streak",
    ))
    anomaly_streak: Streak = field(default_factory=lambda: Streak(
        name="anomaly_streak",
    ))
    attention_needed: bool = False
    top_streak: str | None = None
    headline: str = ""
    next_action: str = ""


def _severity_for(streak_count: int, threshold: int) -> str:
    if streak_count >= threshold * 2:
        return "critical"
    if streak_count >= threshold:
        return "warn"
    return "info"


def _count_loss_streak(
    snapshots: list[dict[str, Any]],
) -> int:
    """Snapshots newest first; count how many of the most
    recent run in stress verdicts."""
    n = 0
    for snap in snapshots:
        v = str(snap.get("verdict") or "no_data")
        if v in _STRESS_VERDICTS:
            n += 1
        else:
            break
    return n


def _count_no_data_streak(
    snapshots: list[dict[str, Any]],
) -> int:
    n = 0
    for snap in snapshots:
        v = str(snap.get("verdict") or "no_data")
        if v == "no_data":
            n += 1
        else:
            break
    return n


def _count_anomaly_streak(
    snapshots: list[dict[str, Any]],
) -> int:
    """Snapshots that carry orphan_action_count >= 5 OR a
    critical_anomaly_count > 0 (best-available proxy when
    snapshots predate explicit anomaly tags)."""
    n = 0
    for snap in snapshots:
        anom = snap.get("critical_anomaly_count", 0)
        orphans = snap.get("orphan_action_count", 0)
        try:
            anom_n = int(anom or 0)
            orph_n = int(orphans or 0)
        except (TypeError, ValueError):
            break
        if anom_n > 0 or orph_n >= 5:
            n += 1
        else:
            break
    return n


def _build_headline(
    report: StreakReport,
    threshold: int,
) -> str:
    streaks = [
        report.loss_streak,
        report.no_data_streak,
        report.anomaly_streak,
    ]
    severe = [
        s for s in streaks
        if s.severity in ("warn", "critical")
    ]
    if not severe:
        return (
            "No persistent stress patterns detected."
        )
    severe.sort(
        key=lambda s: (
            0 if s.severity == "critical" else 1, -s.count,
        ),
    )
    top = severe[0]
    report.top_streak = top.name
    report.attention_needed = True
    return (
        f"ATTENTION: {top.name} = {top.count} consecutive "
        f"snapshot(s) ({top.severity})."
    )


def _build_next_action(report: StreakReport) -> str:
    if not report.attention_needed:
        return (
            "Streaks clean -- continue with the normal "
            "morning ritual."
        )
    name = report.top_streak
    if name == "loss_streak":
        return (
            report.loss_streak.drill
            or "shopai roas + shopai action-critic"
        )
    if name == "no_data_streak":
        return (
            report.no_data_streak.drill
            or "shopai cycle status (cron may be down)"
        )
    if name == "anomaly_streak":
        return (
            report.anomaly_streak.drill
            or "shopai anomalies + shopai engine alerts"
        )
    return "shopai morning-brief"


def detect_streaks(
    *,
    threshold_days: int = 3,
    snapshots_override: list[dict[str, Any]] | None = None,
) -> StreakReport:
    """Scan W963-50 history and emit streak counts."""
    report = StreakReport()
    threshold = max(1, int(threshold_days))

    if snapshots_override is not None:
        snaps = list(snapshots_override)
    else:
        try:
            from engines.agi_earnings_history.store import (
                query,
            )
            snaps = query(days=60, limit=60)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "streak: history raised: %s", exc,
            )
            snaps = []
    report.samples_scanned = len(snaps)

    # loss_streak
    loss_n = _count_loss_streak(snaps)
    report.loss_streak.count = loss_n
    report.loss_streak.severity = _severity_for(
        loss_n, threshold,
    )
    if loss_n > 0:
        report.loss_streak.detail = (
            f"Verdict has been in "
            "{attributed_loss, organic_only} for "
            f"{loss_n} snapshot(s)."
        )
        report.loss_streak.drill = (
            "shopai roas + shopai action-critic + "
            "shopai engine ranking"
        )

    # no_data_streak
    nd_n = _count_no_data_streak(snaps)
    report.no_data_streak.count = nd_n
    report.no_data_streak.severity = _severity_for(
        nd_n, threshold,
    )
    if nd_n > 0:
        report.no_data_streak.detail = (
            f"Verdict has been no_data for {nd_n} "
            "snapshot(s) -- cron / cycle may be broken."
        )
        report.no_data_streak.drill = (
            "shopai cycle status + shopai go-live"
        )

    # anomaly_streak
    an_n = _count_anomaly_streak(snaps)
    report.anomaly_streak.count = an_n
    report.anomaly_streak.severity = _severity_for(
        an_n, threshold,
    )
    if an_n > 0:
        report.anomaly_streak.detail = (
            f"Critical anomaly OR orphan-burst flagged on "
            f"{an_n} consecutive snapshot(s)."
        )
        report.anomaly_streak.drill = (
            "shopai anomalies + shopai engine alerts"
        )

    report.headline = _build_headline(report, threshold)
    report.next_action = _build_next_action(report)
    return report
