"""Run chaos tests against the empire substrate.

Each test:
  1. Patches a substrate piece to fail in a specific way
  2. Calls a consumer engine with empty/synthetic input
  3. Asserts the consumer still returns a valid Pattern Q
     envelope (no crash, no propagated exception)
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

logger = logging.getLogger(__name__)


@dataclass
class ChaosTestResult:
    suite: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ChaosReport:
    suite_filter: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[ChaosTestResult] = field(default_factory=list)


def _is_pattern_q(envelope: Any) -> tuple[bool, str]:
    if not isinstance(envelope, dict):
        return (False, "non-dict")
    required = {"status", "data", "meta", "error"}
    missing = required - set(envelope.keys())
    if missing:
        return (False, f"missing keys: {sorted(missing)}")
    if envelope["status"] not in {"success", "error", "fail"}:
        return (False, f"bad status {envelope['status']!r}")
    return (True, "")


def _run_one(
    suite: str,
    name: str,
    fn,
) -> ChaosTestResult:
    """Execute a single chaos test. Catch all exceptions so
    the chaos run itself can't halt the empire."""
    try:
        ok, detail = fn()
        return ChaosTestResult(
            suite=suite, name=name, passed=ok, detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return ChaosTestResult(
            suite=suite, name=name, passed=False,
            detail=f"chaos test raised: {type(exc).__name__}",
        )


# ── Observation suite ──────────────────────────────────────


def _test_funnel_handles_missing_orders():
    from engines.conversion_funnel import (
        ConversionFunnelEngine,
    )
    with patch(
        "engines.conversion_funnel.analyzer._hydrate_orders",
        return_value=[],
    ), patch(
        "engines.conversion_funnel.analyzer."
        "_hydrate_abandoned",
        return_value=[],
    ):
        r = ConversionFunnelEngine().run({})
    return _is_pattern_q(r)


def _test_trajectory_handles_missing_orders():
    from engines.daily_trajectory import DailyTrajectoryEngine
    with patch(
        "engines.daily_trajectory.analyzer._hydrate_orders",
        return_value=[],
    ):
        r = DailyTrajectoryEngine().run({})
    return _is_pattern_q(r)


def _test_earnings_handles_attribution_failure():
    from engines.earnings_by_engine import (
        EarningsByEngineEngine,
    )
    with patch(
        "engines._revenue_attribution.attribute_revenue",
        side_effect=RuntimeError("attribution down"),
    ):
        r = EarningsByEngineEngine().run({})
    return _is_pattern_q(r)


def _test_strategist_handles_all_observation_failures():
    from engines.store_strategist import StoreStrategistEngine
    # Force EVERY collector to raise. Strategist should still
    # produce a valid envelope with at-least a catch-all rec.
    with patch(
        "engines.conversion_funnel.ConversionFunnelEngine",
        side_effect=RuntimeError("funnel down"),
    ), patch(
        "engines.daily_trajectory.DailyTrajectoryEngine",
        side_effect=RuntimeError("trajectory down"),
    ), patch(
        "engines.earnings_by_engine.EarningsByEngineEngine",
        side_effect=RuntimeError("earnings down"),
    ), patch(
        "engines.checkup.CheckupEngine",
        side_effect=RuntimeError("checkup down"),
    ):
        r = StoreStrategistEngine().run({})
    return _is_pattern_q(r)


def _test_checkup_tolerates_probe_failure():
    from engines.checkup import CheckupEngine
    # Patch one probe to raise — the rest should still produce
    # a valid envelope.
    with patch(
        "engines.checkup.probe._probe_email_connect",
        side_effect=RuntimeError("email probe down"),
    ):
        r = CheckupEngine().run({})
    return _is_pattern_q(r)


# ── Autopilot suite ────────────────────────────────────────


def _test_autopilot_handles_welcome_failure():
    # Welcome stage raises → other stages still run + report
    # still valid.
    from engines.autopilot.runner import run_autopilot
    with patch(
        "engines.autopilot.runner._run_welcome",
        side_effect=RuntimeError("welcome down"),
    ):
        try:
            run_autopilot(confirmed=False, store_id=None)
        except Exception as exc:  # noqa: BLE001
            return (
                False,
                f"autopilot crashed on stage exception: "
                f"{type(exc).__name__}",
            )
    return (True, "stage exception did not halt autopilot")


def _test_autopilot_emergency_pause_blocks_writes():
    from engines.autopilot.runner import run_autopilot
    with patch(
        "engines.autopilot.runner._fleet_emergency_paused",
        return_value=True,
    ):
        report = run_autopilot(
            confirmed=True, store_id=None,
        )
    stages = {s.name: s for s in report.stages}
    welcome_disabled = (
        stages["welcome"].verdict == "disabled"
    )
    reviews_disabled = (
        stages["reviews"].verdict == "disabled"
    )
    if welcome_disabled and reviews_disabled:
        return (True, "emergency marker forced writers off")
    return (
        False,
        f"emergency marker DID NOT block: "
        f"welcome={stages['welcome'].verdict}, "
        f"reviews={stages['reviews'].verdict}",
    )


# ── Cross-store suite ──────────────────────────────────────


def _test_fleet_autopilot_tolerates_per_store_failure():
    from engines.fleet_autopilot.runner import (
        run_fleet_autopilot,
    )
    call_count = {"n": 0}
    def _flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("store 2 broke")
        m = type("R", (), {})()
        m.overall_verdict = "ok"
        m.stages = []
        return m
    with patch(
        "engines.fleet_autopilot.runner._list_fleet",
        return_value=["s1", "s2", "s3"],
    ), patch(
        "engines.autopilot.runner.run_autopilot",
        side_effect=_flaky,
    ):
        r = run_fleet_autopilot(confirmed=False)
    if len(r.by_store) == 3:
        return (True, "all 3 stores reported")
    return (
        False,
        f"expected 3 store outcomes, got {len(r.by_store)}",
    )


def _test_fleet_transfer_auto_tolerates_queue_failure():
    from engines.fleet_transfer_auto import (
        FleetTransferAutoEngine,
    )
    with patch(
        "core.approval.queue.get_approval_queue",
        side_effect=RuntimeError("queue down"),
    ):
        r = FleetTransferAutoEngine().run({})
    return _is_pattern_q(r)


def _test_anomaly_detector_handles_metric_fetch_failure():
    from engines.cross_store_anomaly_detector import (
        CrossStoreAnomalyDetectorEngine,
    )
    with patch(
        "engines.cross_store_anomaly_detector.detector."
        "_store_metrics",
        side_effect=RuntimeError("store probe down"),
    ):
        try:
            r = CrossStoreAnomalyDetectorEngine().run({})
        except Exception as exc:  # noqa: BLE001
            return (
                False,
                f"anomaly crashed: {type(exc).__name__}",
            )
    return _is_pattern_q(r)


# ── Suite registry ─────────────────────────────────────────


_SUITES = {
    "observation": [
        ("funnel_no_orders", _test_funnel_handles_missing_orders),
        (
            "trajectory_no_orders",
            _test_trajectory_handles_missing_orders,
        ),
        (
            "earnings_attribution_failure",
            _test_earnings_handles_attribution_failure,
        ),
        (
            "strategist_all_observation_down",
            _test_strategist_handles_all_observation_failures,
        ),
        (
            "checkup_probe_failure",
            _test_checkup_tolerates_probe_failure,
        ),
    ],
    "autopilot": [
        (
            "welcome_stage_exception",
            _test_autopilot_handles_welcome_failure,
        ),
        (
            "emergency_marker_blocks_writes",
            _test_autopilot_emergency_pause_blocks_writes,
        ),
    ],
    "cross_store": [
        (
            "fleet_autopilot_per_store_exception",
            _test_fleet_autopilot_tolerates_per_store_failure,
        ),
        (
            "fleet_transfer_auto_queue_failure",
            _test_fleet_transfer_auto_tolerates_queue_failure,
        ),
        (
            "anomaly_metric_fetch_failure",
            _test_anomaly_detector_handles_metric_fetch_failure,
        ),
    ],
}


def available_suites() -> list[str]:
    return sorted(_SUITES.keys())


def run_chaos_tests(
    *, suite_filter: str = "",
) -> ChaosReport:
    """Execute one or all suites + aggregate results."""
    report = ChaosReport(suite_filter=suite_filter)
    target = (
        [suite_filter] if suite_filter else list(_SUITES.keys())
    )
    for suite_name in target:
        tests = _SUITES.get(suite_name)
        if tests is None:
            continue
        for name, fn in tests:
            result = _run_one(suite_name, name, fn)
            report.results.append(result)
            report.total += 1
            if result.passed:
                report.passed += 1
            else:
                report.failed += 1
    return report
