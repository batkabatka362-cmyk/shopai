"""Approval queue SLA (service level agreement) tracking.

When operators run 20+ stores, some pending actions sit for
hours/days because operator hasn't gotten to them. The SLA
substrate identifies actions that have aged past the
configured threshold + escalates them so they surface in
empire dashboards / notify webhooks.

## SLA bands

  - on_time: pending < SLA_WARN_HOURS
  - aging: SLA_WARN_HOURS <= pending < SLA_CRITICAL_HOURS
  - breached: pending >= SLA_CRITICAL_HOURS

Defaults: WARN=4h, CRITICAL=24h. Operators tune via env:
  SHOPAI_APPROVAL_SLA_WARN_HOURS=N
  SHOPAI_APPROVAL_SLA_CRITICAL_HOURS=N

## API

  classify_action(action, now) -> SLABand
  compute_sla_report(actions=None) -> SLAReport
    Aggregates pending actions by SLA band, surfaces oldest
    actions per band.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_WARN_HOURS = 4.0
_DEFAULT_CRITICAL_HOURS = 24.0


def warn_threshold_hours() -> float:
    raw = os.environ.get("SHOPAI_APPROVAL_SLA_WARN_HOURS")
    if not raw:
        return _DEFAULT_WARN_HOURS
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_WARN_HOURS


def critical_threshold_hours() -> float:
    raw = os.environ.get("SHOPAI_APPROVAL_SLA_CRITICAL_HOURS")
    if not raw:
        return _DEFAULT_CRITICAL_HOURS
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_CRITICAL_HOURS


@dataclass
class SLAClassification:
    action_id: str
    engine: str
    age_hours: float
    band: str  # on_time / aging / breached

    @property
    def is_breached(self) -> bool:
        return self.band == "breached"


@dataclass
class SLAReport:
    total_pending: int = 0
    on_time: int = 0
    aging: int = 0
    breached: int = 0
    oldest_breach: SLAClassification | None = None
    breached_actions: list[SLAClassification] = field(
        default_factory=list,
    )

    @property
    def has_breaches(self) -> bool:
        return self.breached > 0


def classify_action(
    action: Any,
    *,
    now: float | None = None,
    warn_h: float | None = None,
    critical_h: float | None = None,
) -> SLAClassification | None:
    """Return SLA band for an action.

    Returns None when the action has no parseable
    ``proposed_at`` timestamp.
    """
    if now is None:
        now = time.time()
    if warn_h is None:
        warn_h = warn_threshold_hours()
    if critical_h is None:
        critical_h = critical_threshold_hours()

    proposed_at = getattr(action, "proposed_at", None)
    if proposed_at is None:
        return None
    try:
        proposed_ts = float(proposed_at)
    except (TypeError, ValueError):
        return None
    age_h = max(0.0, (now - proposed_ts) / 3600.0)

    if age_h >= critical_h:
        band = "breached"
    elif age_h >= warn_h:
        band = "aging"
    else:
        band = "on_time"

    return SLAClassification(
        action_id=str(getattr(action, "id", "?")),
        engine=getattr(action, "engine", "unknown"),
        age_hours=round(age_h, 2),
        band=band,
    )


def compute_sla_report(
    actions: list[Any] | None = None,
) -> SLAReport:
    """Build an SLA report over pending actions."""
    if actions is None:
        try:
            from core.approval.queue import get_approval_queue
            actions = (
                get_approval_queue().list_pending(limit=10_000)
                or []
            )
        except Exception:  # noqa: BLE001
            actions = []

    now = time.time()
    warn_h = warn_threshold_hours()
    critical_h = critical_threshold_hours()
    report = SLAReport()

    for a in actions:
        report.total_pending += 1
        c = classify_action(
            a, now=now, warn_h=warn_h, critical_h=critical_h,
        )
        if c is None:
            continue
        if c.band == "on_time":
            report.on_time += 1
        elif c.band == "aging":
            report.aging += 1
        elif c.band == "breached":
            report.breached += 1
            report.breached_actions.append(c)
            if (
                report.oldest_breach is None
                or c.age_hours > report.oldest_breach.age_hours
            ):
                report.oldest_breach = c

    # Sort breached descending by age
    report.breached_actions.sort(
        key=lambda c: -c.age_hours,
    )
    return report
