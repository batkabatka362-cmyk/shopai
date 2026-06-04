"""Collect critical signals across the fleet."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InterventionAlert:
    store_id: str
    signal: str
    severity: str   # critical / high / medium
    headline: str
    detail: str = ""
    drill_command: str = ""
    severity_score: float = 0.0


@dataclass
class InterventionReport:
    total_signals_scanned: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    alerts: list[InterventionAlert] = field(default_factory=list)
    by_store: dict[str, list[InterventionAlert]] = field(
        default_factory=dict,
    )


_SEVERITY_SCORE = {
    "critical": 3.0,
    "high":     2.0,
    "medium":   1.0,
}


def _collect_anomaly_alerts() -> list[InterventionAlert]:
    """Anomaly outliers above 4.0 MAD = critical signal."""
    out: list[InterventionAlert] = []
    try:
        from engines.cross_store_anomaly_detector import (
            CrossStoreAnomalyDetectorEngine,
        )
        result = CrossStoreAnomalyDetectorEngine().run({
            "data": {"mad_threshold": 4.0},
        })
        data = result.get("data") or {}
        for a in data.get("alerts") or []:
            sid = str(a.get("store_id") or "")
            metric = str(a.get("metric") or "")
            dev = float(a.get("deviation_mads") or 0.0)
            direction = str(a.get("direction") or "")
            severity = "critical" if dev >= 6.0 else "high"
            out.append(InterventionAlert(
                store_id=sid,
                signal="anomaly",
                severity=severity,
                headline=(
                    f"{metric} diverges {dev:.1f} MADs "
                    f"{direction}"
                ),
                detail=(
                    f"fleet median={a.get('fleet_median')} "
                    f"value={a.get('value')}"
                ),
                drill_command=(
                    f"shopai strategist --store {sid}"
                ),
                severity_score=(
                    _SEVERITY_SCORE[severity] + dev / 10.0
                ),
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "interventions: anomaly raised: %s", exc,
        )
    return out


def _collect_fleet_strategist_intervene() -> list[InterventionAlert]:
    """Fleet strategist verdict=intervene + revenue>0 stores."""
    out: list[InterventionAlert] = []
    try:
        from engines.fleet_strategist import (
            FleetStrategistEngine,
        )
        result = FleetStrategistEngine().run({})
        data = result.get("data") or {}
        for r in (data.get("by_bucket") or {}).get(
            "intervene_now", []
        ):
            sid = str(r.get("store_id") or "")
            action = str(r.get("top_action") or "")
            drill = str(r.get("top_drill") or "")
            score = float(r.get("fleet_priority") or 0.0)
            severity = "critical" if score >= 2.0 else "high"
            out.append(InterventionAlert(
                store_id=sid,
                signal="strategist_intervene",
                severity=severity,
                headline=f"Strategist: {action}",
                detail=str(
                    r.get("top_reasoning") or "",
                )[:120],
                drill_command=drill,
                severity_score=(
                    _SEVERITY_SCORE[severity] + score
                ),
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "interventions: strategist raised: %s", exc,
        )
    return out


def _collect_autonomy_paused_per_store() -> list[InterventionAlert]:
    """Stores with paused autonomy domains."""
    out: list[InterventionAlert] = []
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        sm = StoreManager()
        for s in (sm.list_stores() or []):
            if not isinstance(s, dict):
                continue
            sid = s.get("store_id")
            if not sid:
                continue
            try:
                report = get_autonomy_status(store_id=sid)
            except Exception:  # noqa: BLE001
                continue
            paused = [
                d.name
                for d in (
                    getattr(report, "domains", []) or []
                )
                if getattr(d, "paused", False)
            ]
            if not paused:
                continue
            out.append(InterventionAlert(
                store_id=sid,
                signal="autonomy_paused",
                severity="high",
                headline=(
                    f"Autonomy paused: {', '.join(paused)}"
                ),
                drill_command=(
                    f"shopai autonomy-status --store {sid}"
                ),
                severity_score=(
                    _SEVERITY_SCORE["high"] + len(paused)
                ),
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "interventions: autonomy raised: %s", exc,
        )
    return out


def _collect_fleet_emergency_marker() -> list[InterventionAlert]:
    """If fleet emergency marker set, surface it."""
    out: list[InterventionAlert] = []
    try:
        from engines.fleet_emergency_pause.state import (
            get_state, is_paused,
        )
        if not is_paused():
            return out
        state = get_state()
        out.append(InterventionAlert(
            store_id="*fleet*",
            signal="fleet_emergency",
            severity="critical",
            headline="FLEET EMERGENCY PAUSE ACTIVE",
            detail=(
                f"paused_at={state.get('paused_at')} "
                f"reason={state.get('reason') or '(none)'}"
            ),
            drill_command=(
                "shopai fleet-emergency --resume --yes"
            ),
            severity_score=10.0,  # always top of list
        ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "interventions: emergency raised: %s", exc,
        )
    return out


def collect_interventions() -> InterventionReport:
    """Aggregate every critical signal across the fleet."""
    report = InterventionReport()
    alerts: list[InterventionAlert] = []
    alerts.extend(_collect_fleet_emergency_marker())
    alerts.extend(_collect_anomaly_alerts())
    alerts.extend(_collect_fleet_strategist_intervene())
    alerts.extend(_collect_autonomy_paused_per_store())

    report.total_signals_scanned = len(alerts)
    report.alerts = sorted(
        alerts,
        key=lambda a: a.severity_score,
        reverse=True,
    )
    for a in report.alerts:
        if a.severity == "critical":
            report.critical_count += 1
        elif a.severity == "high":
            report.high_count += 1
        else:
            report.medium_count += 1
        report.by_store.setdefault(
            a.store_id, [],
        ).append(a)
    return report
