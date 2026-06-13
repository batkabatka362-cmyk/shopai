"""Detect sudden anomalies in the AGI verdict timeline."""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Anomaly:
    type: str
    severity: str   # critical / warn / info
    delta: float
    description: str
    occurred_at: float = 0.0


@dataclass
class AnomalyReport:
    window: int
    sample_count: int
    anomalies: list[Anomaly] = field(default_factory=list)
    headline: str = ""
    next_action: str = ""


def _gather_snapshots(window: int) -> list[dict[str, Any]]:
    try:
        from engines.agi_earnings_history.store import (
            query,
        )
        snaps = query(days=60, limit=max(window * 2, 10))
        return snaps[:window]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: history fetch raised: %s", exc,
        )
        return []


def _mode_verdict(snaps: list[dict[str, Any]]) -> str:
    if not snaps:
        return "no_data"
    counts: dict[str, int] = {}
    for s in snaps:
        v = str(s.get("verdict") or "no_data")
        counts[v] = counts.get(v, 0) + 1
    return max(
        counts.items(), key=lambda kv: kv[1],
    )[0]


def _mad(values: list[float]) -> float:
    """Median absolute deviation, robust against outliers."""
    if not values:
        return 0.0
    med = statistics.median(values)
    devs = [abs(v - med) for v in values]
    return statistics.median(devs)


def _check_verdict_flip(
    snaps: list[dict[str, Any]],
    anomalies: list[Anomaly],
) -> None:
    if len(snaps) < 3:
        return
    # snaps are newest-first
    latest = snaps[0]
    history = snaps[1:]
    mode = _mode_verdict(history)
    latest_v = str(latest.get("verdict") or "no_data")
    if latest_v == mode:
        return
    # Severity: flip away from earning is critical;
    # toward earning is info
    if mode == "earning" and latest_v != "earning":
        sev = "critical"
    elif latest_v == "earning" and mode != "earning":
        sev = "info"
    else:
        sev = "warn"
    anomalies.append(Anomaly(
        type="VERDICT_FLIP",
        severity=sev,
        delta=0.0,
        description=(
            f"Latest verdict={latest_v} but rolling "
            f"mode of last {len(history)} snapshots was "
            f"{mode}."
        ),
        occurred_at=float(latest.get("ts", 0) or 0),
    ))


def _check_profit_outlier(
    snaps: list[dict[str, Any]],
    anomalies: list[Anomaly],
) -> None:
    if len(snaps) < 4:
        return
    latest = snaps[0]
    history = snaps[1:]
    values: list[float] = []
    for s in history:
        try:
            values.append(float(
                s.get("gross_profit", 0) or 0,
            ))
        except (TypeError, ValueError):
            continue
    if not values:
        return
    try:
        latest_v = float(
            latest.get("gross_profit", 0) or 0,
        )
    except (TypeError, ValueError):
        return
    med = statistics.median(values)
    mad = _mad(values)
    dev = abs(latest_v - med)

    # W963-97 fix: pre-fix, mad==0.0 short-circuited and the
    # function returned WITHOUT flagging anything. But mad=0
    # specifically means "history was perfectly stable" -- a
    # zero-variance baseline. Any non-negligible deviation
    # from that stable median IS the outlier we're meant to
    # detect. Pre-fix: empire goes from $0 profit for 13
    # snapshots to -$50k on snapshot 14, NO ANOMALY fires
    # because mad==0 masked it. Post-fix: zero-variance
    # history with a deviating latest emits the anomaly
    # (with a tolerance of $0.50 for floating-point noise).
    if mad == 0.0:
        if dev < 0.5:
            return
        threshold_detail = "stable history (mad=0)"
    else:
        # 3-MAD is roughly 4.45σ for normal data
        if dev < 3.0 * mad:
            return
        threshold_detail = ">=3 MAD"

    direction = "drop" if latest_v < med else "spike"
    sev = "critical" if direction == "drop" else "warn"
    anomalies.append(Anomaly(
        type="PROFIT_OUTLIER",
        severity=sev,
        delta=round(latest_v - med, 2),
        description=(
            f"gross_profit={latest_v:.0f} is a {direction} "
            f"vs rolling median {med:.0f} "
            f"({threshold_detail})."
        ),
        occurred_at=float(latest.get("ts", 0) or 0),
    ))


def _check_attribution_change(
    snaps: list[dict[str, Any]],
    anomalies: list[Anomaly],
) -> None:
    if len(snaps) < 3:
        return
    latest = snaps[0]
    history = snaps[1:]
    values: list[float] = []
    for s in history:
        try:
            values.append(float(
                s.get("attribution_pct", 0) or 0,
            ))
        except (TypeError, ValueError):
            continue
    if not values:
        return
    med = statistics.median(values)
    try:
        latest_pct = float(
            latest.get("attribution_pct", 0) or 0,
        )
    except (TypeError, ValueError):
        return
    delta = latest_pct - med
    if abs(delta) < 50.0:
        return
    if delta < 0:
        anomalies.append(Anomaly(
            type="ATTRIBUTION_COLLAPSE",
            severity="critical",
            delta=round(delta, 1),
            description=(
                f"attribution_pct={latest_pct:.1f}% "
                f"collapsed from rolling median "
                f"{med:.1f}%."
            ),
            occurred_at=float(latest.get("ts", 0) or 0),
        ))
    else:
        anomalies.append(Anomaly(
            type="ATTRIBUTION_SPIKE",
            severity="info",
            delta=round(delta, 1),
            description=(
                f"attribution_pct={latest_pct:.1f}% "
                f"jumped from rolling median "
                f"{med:.1f}%."
            ),
            occurred_at=float(latest.get("ts", 0) or 0),
        ))


def _check_orphan_burst(
    snaps: list[dict[str, Any]],
    anomalies: list[Anomaly],
) -> None:
    if len(snaps) < 2:
        return
    latest = snaps[0]
    previous = snaps[1]
    try:
        cur = int(
            latest.get("orphan_action_count", 0) or 0,
        )
        prev = int(
            previous.get("orphan_action_count", 0) or 0,
        )
    except (TypeError, ValueError):
        return
    if prev <= 2 and cur >= 10:
        anomalies.append(Anomaly(
            type="ORPHAN_BURST",
            severity="warn",
            delta=float(cur - prev),
            description=(
                f"orphan_action_count jumped {prev} -> "
                f"{cur}; AGI is claiming attribution "
                "without matching orders."
            ),
            occurred_at=float(latest.get("ts", 0) or 0),
        ))


def _build_headline(report: AnomalyReport) -> str:
    if not report.anomalies:
        return (
            f"Clean -- no anomalies in last "
            f"{report.window} snapshots."
        )
    crit = sum(
        1 for a in report.anomalies
        if a.severity == "critical"
    )
    warn = sum(
        1 for a in report.anomalies
        if a.severity == "warn"
    )
    info = sum(
        1 for a in report.anomalies
        if a.severity == "info"
    )
    return (
        f"{len(report.anomalies)} anomaly(ies): "
        f"{crit} critical / {warn} warn / {info} info."
    )


def _build_next_action(report: AnomalyReport) -> str:
    if not report.anomalies:
        return "All clear."
    critical = [
        a for a in report.anomalies
        if a.severity == "critical"
    ]
    if critical:
        top = critical[0]
        return (
            f"Critical anomaly {top.type}: drill via "
            "shopai morning-brief + shopai engine alerts."
        )
    return (
        f"Review {len(report.anomalies)} anomaly(ies) -- "
        "shopai week-review for context."
    )


def detect(
    *,
    window: int = 14,
    snaps_override: list[dict[str, Any]] | None = None,
) -> AnomalyReport:
    window = max(3, min(window, 200))
    snaps = (
        snaps_override
        if snaps_override is not None
        else _gather_snapshots(window)
    )
    report = AnomalyReport(
        window=window,
        sample_count=len(snaps),
    )
    _check_verdict_flip(snaps, report.anomalies)
    _check_profit_outlier(snaps, report.anomalies)
    _check_attribution_change(snaps, report.anomalies)
    _check_orphan_burst(snaps, report.anomalies)
    # Sort by severity (critical first), then by recency
    sev_rank = {"critical": 0, "warn": 1, "info": 2}
    report.anomalies.sort(
        key=lambda a: (
            sev_rank.get(a.severity, 3),
            -a.occurred_at,
        ),
    )
    report.headline = _build_headline(report)
    report.next_action = _build_next_action(report)
    return report
