"""Run the autopilot stages.

Each stage is best-effort: a failure logs + records a stage
result but doesn't stop the loop. The aggregate report carries
per-stage verdict + counts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    name: str
    enabled: bool
    fired: bool = False
    verdict: str = "skipped"  # ok / warn / error / skipped / disabled
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutopilotReport:
    confirmed: bool
    store_id: str | None
    stages: list[StageResult] = field(default_factory=list)
    overall_verdict: str = "skipped"


def _env_gate(name: str, default_on: bool = False) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default_on
    return raw.lower() in ("1", "true", "yes", "on")


def _run_welcome(
    confirmed: bool,
) -> StageResult:
    enabled = _env_gate("SHOPAI_AUTOPILOT_WELCOME", False)
    stage = StageResult(name="welcome", enabled=enabled)
    if not confirmed or not enabled:
        stage.verdict = "disabled"
        stage.detail = (
            "set SHOPAI_AUTOPILOT_WELCOME=1 + run with --yes"
        )
        return stage
    try:
        from engines.welcome_series import (
            WelcomeSeriesEngine,
        )
        result = WelcomeSeriesEngine().run({
            "data": {"action": "send-batch"},
        })
        if result.get("status") != "success":
            stage.verdict = "error"
            stage.detail = result.get("error") or "unknown"
            return stage
        data = result.get("data") or {}
        report = data.get("report") or {}
        stage.fired = True
        stage.data = report
        if report.get("failed", 0) > 0:
            stage.verdict = "warn"
            stage.detail = (
                f"sent={report.get('sent', 0)}  "
                f"failed={report.get('failed', 0)}"
            )
        else:
            stage.verdict = "ok"
            stage.detail = f"sent={report.get('sent', 0)}"
        return stage
    except Exception as exc:  # noqa: BLE001
        logger.debug("welcome stage raised: %s", exc)
        stage.verdict = "error"
        stage.detail = (
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )
        return stage


def _run_reviews(
    confirmed: bool,
) -> StageResult:
    enabled = _env_gate("SHOPAI_AUTOPILOT_REVIEWS", False)
    stage = StageResult(name="reviews", enabled=enabled)
    if not confirmed or not enabled:
        stage.verdict = "disabled"
        stage.detail = (
            "set SHOPAI_AUTOPILOT_REVIEWS=1 + run with --yes"
        )
        return stage
    try:
        from engines.review_request import ReviewRequestEngine
        result = ReviewRequestEngine().run({
            "data": {"action": "send-batch"},
        })
        if result.get("status") != "success":
            stage.verdict = "error"
            stage.detail = result.get("error") or "unknown"
            return stage
        data = result.get("data") or {}
        report = data.get("report") or {}
        stage.fired = True
        stage.data = report
        if report.get("failed", 0) > 0:
            stage.verdict = "warn"
            stage.detail = (
                f"sent={report.get('sent', 0)}  "
                f"failed={report.get('failed', 0)}"
            )
        else:
            stage.verdict = "ok"
            stage.detail = f"sent={report.get('sent', 0)}"
        return stage
    except Exception as exc:  # noqa: BLE001
        logger.debug("reviews stage raised: %s", exc)
        stage.verdict = "error"
        stage.detail = (
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )
        return stage


def _run_measure(
    store_id: str | None,
) -> StageResult:
    enabled = _env_gate("SHOPAI_AUTOPILOT_MEASURE", True)
    stage = StageResult(name="measure", enabled=enabled)
    if not enabled:
        stage.verdict = "disabled"
        return stage
    try:
        from engines.earnings_by_engine import (
            EarningsByEngineEngine,
        )
        result = EarningsByEngineEngine().run({
            "data": {
                "window_hours": 168.0,
                "store_id": store_id,
            },
        })
        if result.get("status") != "success":
            stage.verdict = "error"
            stage.detail = result.get("error") or "unknown"
            return stage
        data = result.get("data") or {}
        stage.fired = True
        stage.data = {
            "total_attributed_revenue": data.get(
                "total_attributed_revenue", 0.0,
            ),
            "earning_count": data.get("earning_count", 0),
            "engine_count": len(data.get("engines") or []),
        }
        stage.verdict = "ok"
        rev = stage.data["total_attributed_revenue"]
        stage.detail = (
            f"7d_revenue=${rev:.2f}  "
            f"earning={stage.data['earning_count']}"
        )
        return stage
    except Exception as exc:  # noqa: BLE001
        logger.debug("measure stage raised: %s", exc)
        stage.verdict = "error"
        stage.detail = (
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )
        return stage


def _run_health(
    store_id: str | None,
) -> StageResult:
    enabled = _env_gate("SHOPAI_AUTOPILOT_HEALTH", True)
    stage = StageResult(name="health", enabled=enabled)
    if not enabled:
        stage.verdict = "disabled"
        return stage
    try:
        from engines.checkup import CheckupEngine
        result = CheckupEngine().run({
            "data": {"store_id": store_id},
        })
        if result.get("status") != "success":
            stage.verdict = "error"
            stage.detail = result.get("error") or "unknown"
            return stage
        data = result.get("data") or {}
        verdict = data.get("verdict")
        stage.fired = True
        stage.data = data.get("counts") or {}
        stage.verdict = "ok" if verdict == "ready" else "warn"
        stage.detail = (
            f"verdict={verdict}  "
            f"ready={stage.data.get('ready', 0)}/"
            f"{data.get('engine_count', 0)}"
        )
        return stage
    except Exception as exc:  # noqa: BLE001
        logger.debug("health stage raised: %s", exc)
        stage.verdict = "error"
        stage.detail = (
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )
        return stage


def _compute_overall(stages: list[StageResult]) -> str:
    # Severity: error > warn > ok > disabled > skipped.
    sev = {
        "error": 0, "warn": 1, "ok": 2,
        "disabled": 3, "skipped": 4,
    }
    worst = "skipped"
    for s in stages:
        if sev.get(s.verdict, 4) < sev.get(worst, 4):
            worst = s.verdict
    return worst


def _fleet_emergency_paused() -> bool:
    """Best-effort check of the fleet emergency marker.
    Default to NOT paused when the substrate isn't available
    (engine module missing in older deployments) so legacy
    flows keep working."""
    try:
        from engines.fleet_emergency_pause.state import (
            is_paused,
        )
        return bool(is_paused())
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autopilot: fleet_emergency probe raised: %s", exc,
        )
        return False


def run_autopilot(
    *, confirmed: bool, store_id: str | None,
) -> AutopilotReport:
    """Execute all 4 stages in order. Returns the aggregate.

    Fleet emergency check: if the marker is set, write stages
    (welcome, reviews) are forced into disabled state. Read
    stages (measure, health) still run so the operator can
    diagnose during the pause."""
    report = AutopilotReport(
        confirmed=confirmed, store_id=store_id,
    )
    fleet_paused = _fleet_emergency_paused()
    if fleet_paused:
        # Override confirmed for write stages -- they pretend
        # the operator didn't approve so they short-circuit.
        write_confirmed = False
    else:
        write_confirmed = confirmed
    # W963-34 chaos resilience: each stage wrapped so a stage
    # function that itself raises (rather than returning an
    # error StageResult) does NOT halt the autopilot loop.
    def _safe_stage(name, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "autopilot: stage %s raised: %s", name, exc,
            )
            return StageResult(
                name=name, enabled=True,
                verdict="error",
                detail=(
                    f"stage exception: {type(exc).__name__}"
                ),
            )
    report.stages = [
        _safe_stage("welcome", _run_welcome, write_confirmed),
        _safe_stage("reviews", _run_reviews, write_confirmed),
        _safe_stage("measure", _run_measure, store_id),
        _safe_stage("health", _run_health, store_id),
    ]
    if fleet_paused:
        # Stamp the write stages with the emergency reason.
        for s in report.stages[:2]:
            if s.verdict == "disabled":
                s.detail = (
                    "fleet emergency pause is active"
                )
    report.overall_verdict = _compute_overall(report.stages)
    return report
