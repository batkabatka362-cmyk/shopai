"""Scan anomaly alerts + auto-pause outlier stores.

For each alert above min_deviation:
  - For each engine in the pause list:
    - core.approval.quarantine.add_alert_pause(engine, store_id)
  - Skip if already paused for that (engine, store)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_PAUSE_ENGINES = (
    "welcome_series",
    "review_request",
    "loyalty",
    "discount_strategy",
    "ads_launcher",
)


@dataclass
class QuarantineDecision:
    store_id: str
    metric: str
    deviation_mads: float
    direction: str
    engines_paused: list[str] = field(default_factory=list)
    engines_skipped_existing: list[str] = field(
        default_factory=list,
    )
    skip_reason: str = ""


@dataclass
class AnomalyQuarantineReport:
    confirmed: bool
    min_deviation: float
    pause_engines: list[str]
    alerts_scanned: int = 0
    eligible_alerts: int = 0
    decisions: list[QuarantineDecision] = field(
        default_factory=list,
    )
    total_pauses_added: int = 0
    skip_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _bump_skip(
    report: AnomalyQuarantineReport, reason: str,
) -> None:
    report.skip_count += 1
    report.skip_reasons[reason] = (
        report.skip_reasons.get(reason, 0) + 1
    )


def _run_anomaly_scan(
    mad_threshold: float,
) -> list[dict[str, Any]]:
    """Pull anomaly alerts via the existing detector."""
    try:
        from engines.cross_store_anomaly_detector import (
            CrossStoreAnomalyDetectorEngine,
        )
        result = CrossStoreAnomalyDetectorEngine().run({
            "data": {"mad_threshold": mad_threshold},
        })
        if result.get("status") != "success":
            return []
        return list(
            (result.get("data") or {}).get("alerts") or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly_quarantine: scan raised: %s", exc,
        )
        return []


def _already_paused(
    state_alert_paused: Any,
    engine: str,
    store_id: str,
) -> bool:
    """Check if (engine, store) tuple already in alert_paused."""
    if state_alert_paused is None:
        return False
    for entry in state_alert_paused:
        if isinstance(entry, tuple) and len(entry) == 2:
            e, s = entry
            if e == engine and s == store_id:
                return True
            # Fleet-wide pause for the engine covers any store
            if e == engine and s is None:
                return True
        elif isinstance(entry, str):
            # Legacy format: just engine name = fleet-wide
            if entry == engine:
                return True
    return False


def _add_pause(
    engine: str,
    store_id: str,
) -> bool:
    """Best-effort call to add_alert_pause. Returns True on
    successful pause, False on test-env / no substrate."""
    try:
        from core.approval.quarantine import (
            add_alert_pause,
        )
        add_alert_pause(engine, store_id=store_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly_quarantine: pause add raised: %s", exc,
        )
        return False


def _load_alert_pause_set() -> Any:
    """Pull the current alert_paused set from state. Returns
    None on failure."""
    try:
        from core.approval.quarantine import load_state
        state = load_state()
        return getattr(state, "alert_paused", None)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly_quarantine: state load raised: %s", exc,
        )
        return None


def run_quarantine(
    *,
    confirmed: bool,
    min_deviation: float = 4.0,
    pause_engines: list[str] | None = None,
    alerts: list[dict[str, Any]] | None = None,
) -> AnomalyQuarantineReport:
    """Scan alerts + per-eligible pause the listed engines."""
    pause_list = list(
        pause_engines if pause_engines is not None
        else _DEFAULT_PAUSE_ENGINES
    )
    report = AnomalyQuarantineReport(
        confirmed=confirmed,
        min_deviation=max(0.5, float(min_deviation)),
        pause_engines=pause_list,
    )

    if alerts is None:
        alerts = _run_anomaly_scan(
            mad_threshold=report.min_deviation,
        )
    report.alerts_scanned = len(alerts)

    if not alerts:
        return report

    state_alert_paused = _load_alert_pause_set()

    seen_stores: set[str] = set()
    for a in alerts:
        if not isinstance(a, dict):
            continue
        deviation = float(a.get("deviation_mads") or 0.0)
        if deviation < report.min_deviation:
            _bump_skip(report, "below_threshold")
            continue
        sid = str(a.get("store_id") or "")
        if not sid:
            _bump_skip(report, "no_store_id")
            continue
        report.eligible_alerts += 1
        # Dedupe per-store across multiple metric alerts
        if sid in seen_stores:
            _bump_skip(report, "duplicate_store")
            continue
        seen_stores.add(sid)

        decision = QuarantineDecision(
            store_id=sid,
            metric=str(a.get("metric") or ""),
            deviation_mads=deviation,
            direction=str(a.get("direction") or ""),
        )

        if not confirmed:
            decision.skip_reason = "dry_run"
            report.decisions.append(decision)
            _bump_skip(report, "dry_run")
            continue

        for engine in pause_list:
            if _already_paused(
                state_alert_paused, engine, sid,
            ):
                decision.engines_skipped_existing.append(
                    engine,
                )
                continue
            if _add_pause(engine, sid):
                decision.engines_paused.append(engine)
                report.total_pauses_added += 1
            else:
                # Don't increment skip_count here -- the alert
                # itself counted; this is per-engine attempt.
                pass
        # Refresh state for next iteration (other stores may
        # share the same engine).
        state_alert_paused = _load_alert_pause_set()
        report.decisions.append(decision)

    return report


def default_pause_engines() -> tuple[str, ...]:
    return _DEFAULT_PAUSE_ENGINES
