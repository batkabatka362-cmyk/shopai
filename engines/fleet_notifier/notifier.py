"""Collect critical empire events + dispatch through the
existing engines._notify substrate.

Event taxonomy:
  fleet_emergency       critical (cooldown 24h)
  critical_intervention critical (cooldown 1h)
  anomaly_outlier       high     (cooldown 6h)
  quarantine_triggered  high     (cooldown 12h)
  calibrator_blocked    medium   (cooldown 24h)
  cycle_failed          high     (cooldown 1h)

Each event has a unique (kind, scope) key so per-store
versions don't share cooldown with the fleet-wide version.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import state as state_mod

logger = logging.getLogger(__name__)


_DEFAULT_COOLDOWNS = {
    "fleet_emergency":       86400.0,   # 24h
    "critical_intervention": 3600.0,    # 1h
    "anomaly_outlier":       21600.0,   # 6h
    "quarantine_triggered":  43200.0,   # 12h
    "calibrator_blocked":    86400.0,   # 24h
    "cycle_failed":          3600.0,    # 1h
}


_KIND_SEVERITY = {
    "fleet_emergency":       "critical",
    "critical_intervention": "critical",
    "anomaly_outlier":       "high",
    "quarantine_triggered":  "high",
    "calibrator_blocked":    "medium",
    "cycle_failed":          "high",
}


@dataclass
class CandidateEvent:
    kind: str
    scope: str
    severity: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DispatchResult:
    kind: str
    scope: str
    sent: bool = False
    cooldown_remaining: float = 0.0
    skip_reason: str = ""
    error: str = ""


@dataclass
class NotifyReport:
    confirmed: bool
    kind_filter: str
    candidates_scanned: int = 0
    eligible_count: int = 0
    sent_count: int = 0
    skip_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    dispatches: list[DispatchResult] = field(default_factory=list)


def _bump_skip(report: NotifyReport, reason: str) -> None:
    report.skip_count += 1
    report.skip_reasons[reason] = (
        report.skip_reasons.get(reason, 0) + 1
    )


def _collect_emergency() -> list[CandidateEvent]:
    out: list[CandidateEvent] = []
    try:
        from engines.fleet_emergency_pause.state import (
            get_state, is_paused,
        )
        if not is_paused():
            return out
        state = get_state()
        out.append(CandidateEvent(
            kind="fleet_emergency",
            scope="fleet",
            severity="critical",
            message=(
                "Fleet emergency pause is ACTIVE. Writers "
                "halted across all stores."
            ),
            context={
                "paused_at": state.get("paused_at", ""),
                "paused_by": state.get("paused_by", ""),
                "reason": state.get("reason", ""),
            },
        ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_notifier: emergency raised: %s", exc,
        )
    return out


def _collect_interventions() -> list[CandidateEvent]:
    out: list[CandidateEvent] = []
    try:
        from engines.fleet_intervention_alerts import (
            FleetInterventionAlertsEngine,
        )
        result = FleetInterventionAlertsEngine().run({})
        data = result.get("data") or {}
        critical = int(data.get("critical_count", 0))
        if critical == 0:
            return out
        alerts = data.get("alerts") or []
        # Per-store cooldown so different stores' critical
        # alerts don't share the same key.
        for a in alerts:
            if a.get("severity") != "critical":
                continue
            sid = str(a.get("store_id") or "*")
            out.append(CandidateEvent(
                kind="critical_intervention",
                scope=sid,
                severity="critical",
                message=(
                    f"Critical intervention store={sid}: "
                    f"{a.get('headline', '')}"
                ),
                context={
                    "signal": a.get("signal", ""),
                    "drill_command": a.get(
                        "drill_command", "",
                    ),
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_notifier: interventions raised: %s",
            exc,
        )
    return out


def _collect_anomaly_outliers() -> list[CandidateEvent]:
    out: list[CandidateEvent] = []
    try:
        from engines.cross_store_anomaly_detector import (
            CrossStoreAnomalyDetectorEngine,
        )
        result = CrossStoreAnomalyDetectorEngine().run({
            "data": {"mad_threshold": 4.0},
        })
        data = result.get("data") or {}
        alerts = data.get("alerts") or []
        for a in alerts:
            sid = str(a.get("store_id") or "*")
            metric = str(a.get("metric") or "?")
            dev = float(a.get("deviation_mads") or 0.0)
            out.append(CandidateEvent(
                kind="anomaly_outlier",
                scope=f"{sid}::{metric}",
                severity="high",
                message=(
                    f"Anomaly outlier store={sid} "
                    f"metric={metric}: {dev:.1f} MADs "
                    f"{a.get('direction', '')}"
                ),
                context={
                    "store_id": sid,
                    "metric": metric,
                    "deviation_mads": dev,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_notifier: anomaly raised: %s", exc,
        )
    return out


def _collect_calibrator_blocked() -> list[CandidateEvent]:
    out: list[CandidateEvent] = []
    try:
        from engines.confidence_calibrator import (
            ConfidenceCalibratorEngine,
        )
        result = ConfidenceCalibratorEngine().run({})
        data = result.get("data") or {}
        blocked = []
        for c in data.get("calibrations") or []:
            if c.get("band") == "blocked":
                blocked.append(c)
        for c in blocked:
            eng = c.get("engine", "?")
            ratio = float(c.get("positive_ratio") or 0.0)
            out.append(CandidateEvent(
                kind="calibrator_blocked",
                scope=f"{c.get('store_id') or 'fleet'}::{eng}",
                severity="medium",
                message=(
                    f"Engine {eng} BLOCKED -- positive "
                    f"ratio {ratio*100:.0f}% over "
                    f"{c.get('sample_size')} samples."
                ),
                context={
                    "engine": eng,
                    "positive_ratio": ratio,
                    "sample_size": c.get("sample_size"),
                    "store_id": c.get("store_id"),
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_notifier: calibrator raised: %s", exc,
        )
    return out


def _dispatch_event(event: CandidateEvent) -> tuple[bool, str]:
    """Push the event through engines._notify substrate.
    Returns (sent, error_string)."""
    try:
        # The _notify module's webhook URL + dry-run check is
        # consulted directly so we get the same behavior as
        # the existing notify-check CLI.
        import os
        from urllib.parse import urlparse
        url = os.environ.get(
            "SHOPAI_NOTIFY_WEBHOOK_URL", "",
        ).strip()
        if not url:
            return (False, "no_webhook_url")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return (False, "invalid_webhook_url")
        try:
            import requests
        except ImportError:
            return (False, "requests_missing")
        try:
            resp = requests.post(
                url,
                json={
                    "kind": event.kind,
                    "scope": event.scope,
                    "severity": event.severity,
                    "message": event.message,
                    "context": event.context,
                },
                timeout=10.0,
            )
            if 200 <= resp.status_code < 300:
                return (True, "")
            return (
                False,
                f"http_{resp.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return (
                False,
                f"http_error: {type(exc).__name__}",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_notifier: dispatch raised: %s", exc,
        )
        return (False, f"dispatch_error: {type(exc).__name__}")


def run_notifier(
    *,
    confirmed: bool,
    kind_filter: str = "",
    cooldowns: dict[str, float] | None = None,
) -> NotifyReport:
    """Scan + dispatch eligible candidates."""
    cd = dict(cooldowns or _DEFAULT_COOLDOWNS)
    report = NotifyReport(
        confirmed=confirmed,
        kind_filter=kind_filter,
    )

    candidates: list[CandidateEvent] = []
    candidates.extend(_collect_emergency())
    candidates.extend(_collect_interventions())
    candidates.extend(_collect_anomaly_outliers())
    candidates.extend(_collect_calibrator_blocked())

    report.candidates_scanned = len(candidates)

    for ev in candidates:
        if kind_filter and ev.kind != kind_filter:
            _bump_skip(report, "kind_filter")
            continue
        # Per-kind cooldown
        cooldown = cd.get(ev.kind, 3600.0)
        remaining = state_mod.cooldown_remaining(
            ev.kind, cooldown, scope=ev.scope,
        )
        dispatch = DispatchResult(
            kind=ev.kind, scope=ev.scope,
        )
        if remaining > 0:
            dispatch.cooldown_remaining = round(
                remaining, 1,
            )
            dispatch.skip_reason = "cooldown_active"
            report.dispatches.append(dispatch)
            _bump_skip(report, "cooldown_active")
            continue
        report.eligible_count += 1
        if not confirmed:
            dispatch.skip_reason = "dry_run"
            report.dispatches.append(dispatch)
            _bump_skip(report, "dry_run")
            continue
        # Live dispatch
        sent, err = _dispatch_event(ev)
        dispatch.sent = sent
        dispatch.error = err
        if sent:
            report.sent_count += 1
            state_mod.mark_sent(ev.kind, ev.scope)
        else:
            dispatch.skip_reason = err or "send_failed"
            _bump_skip(report, dispatch.skip_reason)
        report.dispatches.append(dispatch)

    return report


def default_cooldowns() -> dict[str, float]:
    return dict(_DEFAULT_COOLDOWNS)


def kind_severity() -> dict[str, str]:
    return dict(_KIND_SEVERITY)
