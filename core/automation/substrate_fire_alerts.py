"""Per-domain substrate-fire degradation alerter (W849).

Reads the W847 KPI substrate + flags domains whose recent
success rate dropped below a threshold OR error count climbed
above a threshold.

Thresholds are env-overridable so operators can tune sensitivity
per fleet:

  SHOPAI_AUTONOMY_ALERT_MIN_SUCCESS_RATE  (default 0.50)
  SHOPAI_AUTONOMY_ALERT_MAX_ERRORS        (default 3)
  SHOPAI_AUTONOMY_ALERT_MIN_SAMPLE        (default 3)

The min_sample threshold prevents alerts on cold-start /
low-volume domains where a single error pegs the rate at 0%.

Returns ``FireAlert`` dataclasses ready for consumption by the
W850 notify + daily-brief integrations.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from core.automation.substrate_fire_kpi import (
    DomainFireKPI,
    compute_fire_kpis,
)

logger = logging.getLogger(__name__)


def _min_success_rate() -> float:
    raw = os.environ.get(
        "SHOPAI_AUTONOMY_ALERT_MIN_SUCCESS_RATE", "0.50",
    )
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.50


def _max_errors() -> int:
    raw = os.environ.get(
        "SHOPAI_AUTONOMY_ALERT_MAX_ERRORS", "3",
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 3


def _min_sample() -> int:
    raw = os.environ.get(
        "SHOPAI_AUTONOMY_ALERT_MIN_SAMPLE", "3",
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


@dataclass
class FireAlert:
    domain: str
    kind: str  # "low_success_rate" | "high_error_count"
    severity: str  # "warn" | "critical"
    reason: str
    success_rate: float = 1.0
    errors: int = 0
    sample_size: int = 0


@dataclass
class FireAlertsReport:
    window_hours: float = 168.0
    store_id: str | None = None
    alerts: list[FireAlert] = field(default_factory=list)
    domains_evaluated: int = 0
    config: dict = field(default_factory=dict)

    @property
    def has_alerts(self) -> bool:
        return len(self.alerts) > 0

    @property
    def critical_count(self) -> int:
        return sum(
            1 for a in self.alerts if a.severity == "critical"
        )

    @property
    def warn_count(self) -> int:
        return sum(
            1 for a in self.alerts if a.severity == "warn"
        )


def _evaluate(
    kpi: DomainFireKPI,
    min_rate: float,
    max_err: int,
    min_sample: int,
) -> list[FireAlert]:
    """Return zero, one, or two alerts for a single domain KPI."""
    out: list[FireAlert] = []
    actionable = kpi.fired + kpi.errors
    if actionable < min_sample:
        return out

    if kpi.success_rate < min_rate:
        out.append(FireAlert(
            domain=kpi.domain,
            kind="low_success_rate",
            severity=(
                "critical" if kpi.success_rate < min_rate / 2
                else "warn"
            ),
            reason=(
                f"success_rate={kpi.success_rate * 100:.0f}% "
                f"< threshold {min_rate * 100:.0f}% "
                f"(sample={actionable})"
            ),
            success_rate=kpi.success_rate,
            errors=kpi.errors,
            sample_size=actionable,
        ))

    if kpi.errors > max_err:
        out.append(FireAlert(
            domain=kpi.domain,
            kind="high_error_count",
            severity=(
                "critical" if kpi.errors >= max_err * 2
                else "warn"
            ),
            reason=(
                f"errors={kpi.errors} > threshold {max_err} "
                f"(sample={actionable})"
            ),
            success_rate=kpi.success_rate,
            errors=kpi.errors,
            sample_size=actionable,
        ))
    return out


def compute_fire_alerts(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> FireAlertsReport:
    """Walk the per-domain KPIs + flag degradation."""
    report = FireAlertsReport(
        window_hours=window_hours,
        store_id=store_id,
    )
    min_rate = _min_success_rate()
    max_err = _max_errors()
    min_sample = _min_sample()
    report.config = {
        "min_success_rate": min_rate,
        "max_errors": max_err,
        "min_sample": min_sample,
    }
    kpi_report = compute_fire_kpis(
        window_hours=window_hours,
        store_id=store_id,
    )
    for k in kpi_report.per_domain:
        report.domains_evaluated += 1
        report.alerts.extend(
            _evaluate(k, min_rate, max_err, min_sample),
        )

    # W853: persist this firing to alert history for the
    # auto-disarm bridge + multi-day trend analysis.
    if report.alerts:
        try:
            from core.automation.substrate_fire_alert_history import (  # noqa
                record_alerts,
            )
            record_alerts(report.alerts, store_id=store_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "fire-alert history record raised: %s", exc,
            )

    return report
