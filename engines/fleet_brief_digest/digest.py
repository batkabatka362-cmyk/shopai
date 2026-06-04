"""Synthesize the morning digest."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DigestSection:
    name: str
    headline: str
    detail: list[str] = field(default_factory=list)


@dataclass
class DigestReport:
    fleet_verdict: str = "no_data"
    fleet_size: int = 0
    fleet_revenue_7d: float = 0.0
    earning_count: int = 0
    intervene_count: int = 0
    critical_interventions: int = 0
    emergency_active: bool = False
    sections: list[DigestSection] = field(default_factory=list)
    top_actions: list[str] = field(default_factory=list)


def _emergency_section() -> tuple[bool, DigestSection | None]:
    try:
        from engines.fleet_emergency_pause.state import (
            get_state, is_paused,
        )
        if not is_paused():
            return (False, None)
        state = get_state()
        return (True, DigestSection(
            name="EMERGENCY",
            headline=(
                "FLEET EMERGENCY PAUSE ACTIVE — writers halted "
                "across all stores"
            ),
            detail=[
                f"paused_at: {state.get('paused_at', '?')}",
                f"paused_by: {state.get('paused_by', '?')}",
                f"reason: {state.get('reason') or '(none)'}",
                (
                    "Resume: shopai fleet-emergency "
                    "--resume --yes"
                ),
            ],
        ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: emergency check raised: %s", exc,
        )
        return (False, None)


def _fleet_state_section(
    report: DigestReport,
) -> DigestSection | None:
    try:
        from engines.fleet_strategist import (
            FleetStrategistEngine,
        )
        result = FleetStrategistEngine().run({})
        data = result.get("data") or {}
        verdict = data.get("fleet_verdict", "no_data")
        total = int(data.get("total_stores", 0))
        with_data = int(data.get("stores_with_data", 0))
        by_bucket = data.get("by_bucket") or {}
        intervene = len(by_bucket.get("intervene_now", []))
        active = len(by_bucket.get("active", []))
        cold = len(by_bucket.get("cold_start", []))
        report.fleet_verdict = verdict
        report.fleet_size = total
        report.earning_count = active
        report.intervene_count = intervene
        return DigestSection(
            name="FLEET STATE",
            headline=(
                f"{verdict.replace('_', ' ')}: "
                f"{total} store(s) "
                f"({with_data} with data)"
            ),
            detail=[
                f"intervene_now: {intervene}",
                f"active (earning): {active}",
                f"cold_start: {cold}",
                f"quiet: {len(by_bucket.get('quiet', []))}",
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: fleet_strategist raised: %s", exc,
        )
        return None


def _interventions_section(
    report: DigestReport,
) -> DigestSection | None:
    try:
        from engines.fleet_intervention_alerts import (
            FleetInterventionAlertsEngine,
        )
        result = FleetInterventionAlertsEngine().run({})
        data = result.get("data") or {}
        critical = int(data.get("critical_count", 0))
        high = int(data.get("high_count", 0))
        report.critical_interventions = critical
        alerts = data.get("alerts") or []
        if not alerts:
            return DigestSection(
                name="INTERVENTIONS",
                headline="No critical signals. Fleet stable.",
            )
        details = []
        for a in alerts[:5]:
            details.append(
                f"[{a.get('severity', '?')}] "
                f"{a.get('store_id', '?')}: "
                f"{a.get('headline', '')}"
            )
        return DigestSection(
            name="INTERVENTIONS",
            headline=(
                f"{critical} critical + {high} high signals"
            ),
            detail=details,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: interventions raised: %s", exc,
        )
        return None


def _earnings_section(
    report: DigestReport,
) -> DigestSection | None:
    try:
        from engines.earnings_by_engine import (
            EarningsByEngineEngine,
        )
        result = EarningsByEngineEngine().run({
            "data": {"window_hours": 168.0},
        })
        data = result.get("data") or {}
        total_rev = float(
            data.get("total_attributed_revenue") or 0.0,
        )
        earning = int(data.get("earning_count") or 0)
        report.fleet_revenue_7d = total_rev
        engines = data.get("engines") or []
        top_earning = sorted(
            [e for e in engines if e.get("verdict") == "earning"],
            key=lambda e: e.get("attributed_revenue", 0.0),
            reverse=True,
        )[:3]
        details = [
            f"7d total: ${total_rev:.2f}",
            f"earning engines: {earning}",
        ]
        for e in top_earning:
            details.append(
                f"  {e.get('engine')}: "
                f"${e.get('attributed_revenue', 0):.2f}"
            )
        return DigestSection(
            name="EARNINGS (7d)",
            headline=(
                f"${total_rev:.2f} from "
                f"{earning} earning engine(s)"
            ),
            detail=details,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: earnings raised: %s", exc,
        )
        return None


def _substrate_section(
    report: DigestReport,
) -> DigestSection | None:
    try:
        from engines.checkup import CheckupEngine
        result = CheckupEngine().run({})
        data = result.get("data") or {}
        verdict = data.get("verdict", "unknown")
        counts = data.get("counts") or {}
        return DigestSection(
            name="SUBSTRATE",
            headline=f"verdict={verdict}",
            detail=[
                f"ready: {counts.get('ready', 0)}",
                f"partial: {counts.get('partial', 0)}",
                f"missing: {counts.get('missing', 0)}",
                f"error: {counts.get('error', 0)}",
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: substrate raised: %s", exc,
        )
        return None


def _compute_top_actions(report: DigestReport) -> list[str]:
    """Top 3 strategic actions based on the digest."""
    out: list[str] = []
    if report.emergency_active:
        out.append(
            "Investigate emergency cause + resume: "
            "shopai fleet-emergency --resume --yes"
        )
        return out
    if report.critical_interventions > 0:
        out.append(
            f"Address {report.critical_interventions} "
            "critical intervention(s): shopai interventions"
        )
    if report.intervene_count > 0:
        out.append(
            "Fleet has intervene_now stores: "
            "shopai fleet-strategist --verdict intervene"
        )
    if report.earning_count == 0 and report.fleet_size > 0:
        out.append(
            "Fleet not earning yet. Run: "
            "shopai fleet-autopilot --yes "
            "(after wiring credentials)"
        )
    if not out:
        out.append(
            "Fleet stable. Optional: "
            "shopai cycle run --yes for routine cycle."
        )
    return out[:3]


def assemble_digest() -> DigestReport:
    """Build the full digest."""
    report = DigestReport()

    # Emergency takes top of brief
    emergency_active, em_section = _emergency_section()
    report.emergency_active = emergency_active
    if em_section:
        report.sections.append(em_section)

    fs_section = _fleet_state_section(report)
    if fs_section:
        report.sections.append(fs_section)

    iv_section = _interventions_section(report)
    if iv_section:
        report.sections.append(iv_section)

    er_section = _earnings_section(report)
    if er_section:
        report.sections.append(er_section)

    sub_section = _substrate_section(report)
    if sub_section:
        report.sections.append(sub_section)

    report.top_actions = _compute_top_actions(report)
    return report
