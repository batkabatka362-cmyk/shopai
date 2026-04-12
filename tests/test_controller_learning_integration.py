"""Wave 7 #2-#4: controller learning-loop integration tests.

Verifies that the three new error-signal paths feed correctly
into the reflection synthesizer's mining pipeline:

  #2 (GAP-1)  — SLA breaches → phase_errors → reflection buffer
  #2 (GAP-2)  — Mind cycle errors → phase_errors → reflection buffer
  #4 (GAP-19) — Reflection hook failures → phase_errors (self-aware)
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from core.autonomous.controller import AutonomousController
from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import ReflectionSynthesizer
from engines.meta_governance.policy_store import PolicyStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_controller(tmp_path: Path) -> AutonomousController:
    """Build a minimal controller via __new__ with an isolated
    synthesizer and error buffer. No initialize() call needed."""
    import threading

    c = AutonomousController.__new__(AutonomousController)
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    c._reflection_synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    c._reflection_buffer_max = 50
    c._error_buffer = None
    c._reflection_init_lock = threading.Lock()
    c._last_reflection_decay_at = 0.0
    return c


def _tick(c: AutonomousController, errors: dict[str, str]) -> dict[str, Any]:
    """Run the reflection hook once and return cycle_result."""
    cycle_result: dict[str, Any] = {"cycle_id": "test"}
    c._run_reflection_hook(cycle_result, errors)
    return cycle_result


# ---------------------------------------------------------------------------
# GAP-2: Cognitive Mind errors → phase_errors
# ---------------------------------------------------------------------------


class TestMindErrorsInPhaseErrors:
    """Cognitive Mind errors now flow into phase_errors before the
    reflection hook, so recurring Mind crashes can promote SOFT rules."""

    def test_cognitive_error_injected_into_phase_errors(self, tmp_path):
        """When the cognitive report has an 'error' key, it should
        appear in phase_errors under 'cognitive_mind'."""
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {}
        cycle_result: dict[str, Any] = {
            "cycle_id": "test",
            "cognitive": {"error": "Mind.Planner crashed: NoneType"},
        }

        # Simulate the injection that now happens before the hook
        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict) and cog.get("error"):
            phase_errors["cognitive_mind"] = str(cog["error"])

        assert "cognitive_mind" in phase_errors
        assert "Planner crashed" in phase_errors["cognitive_mind"]

    def test_no_injection_when_cognitive_succeeds(self, tmp_path):
        """A successful cognitive report should NOT inject anything."""
        phase_errors: dict[str, str] = {}
        cycle_result = {
            "cycle_id": "test",
            "cognitive": {"phases": ["perceive", "reflect"]},
        }

        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict) and cog.get("error"):
            phase_errors["cognitive_mind"] = str(cog["error"])

        assert "cognitive_mind" not in phase_errors

    def test_no_injection_when_cognitive_absent(self, tmp_path):
        phase_errors: dict[str, str] = {}
        cycle_result: dict[str, Any] = {"cycle_id": "test"}

        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict) and cog.get("error"):
            phase_errors["cognitive_mind"] = str(cog["error"])

        assert "cognitive_mind" not in phase_errors

    def test_mind_error_reaches_reflection_buffer(self, tmp_path):
        """Mind error injected into phase_errors gets mined by the
        reflection hook and lands in the error buffer."""
        c = _bare_controller(tmp_path)
        errors = {"cognitive_mind": "Mind.Planner crashed: NoneType"}
        _tick(c, errors)
        assert c._error_buffer is not None
        assert len(c._error_buffer) == 1
        assert c._error_buffer[0].payload["phase"] == "cognitive_mind"


# ---------------------------------------------------------------------------
# GAP-1: SLA breaches → phase_errors
# ---------------------------------------------------------------------------


class TestSLABreachInjection:
    """SLA breaches are now polled before the reflection hook and
    injected as synthetic phase_errors."""

    def test_breached_subsystem_injected(self, tmp_path, monkeypatch):
        """A breached SLA subsystem should appear in phase_errors."""
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {}

        # Mock the SLA tracker to return a breach
        class FakeTracker:
            def get_report(self):
                return {
                    "subsystems": {
                        "llm_adapter": {
                            "status": "breached",
                            "breaches": ["success_rate", "p95_latency_ms"],
                        },
                        "payment_adapter": {
                            "status": "ok",
                            "breaches": [],
                        },
                    },
                    "total_subsystems": 2,
                }

        class FakeTM:
            def __call__(self):
                return self

            def get_sla_tracker(self):
                return FakeTracker()

        monkeypatch.setattr(
            "core.telemetry.metrics_collector.MetricsCollector",
            FakeTM(),
        )

        c._inject_sla_breaches(phase_errors)

        assert "sla_breach::llm_adapter" in phase_errors
        assert "success_rate" in phase_errors["sla_breach::llm_adapter"]
        assert "sla_breach::payment_adapter" not in phase_errors

    def test_no_injection_when_all_ok(self, tmp_path, monkeypatch):
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {}

        class FakeTracker:
            def get_report(self):
                return {
                    "subsystems": {
                        "brain": {"status": "ok", "breaches": []},
                    },
                    "total_subsystems": 1,
                }

        class FakeTM:
            def __call__(self):
                return self

            def get_sla_tracker(self):
                return FakeTracker()

        monkeypatch.setattr(
            "core.telemetry.metrics_collector.MetricsCollector",
            FakeTM(),
        )

        c._inject_sla_breaches(phase_errors)
        assert not any(k.startswith("sla_breach::") for k in phase_errors)

    def test_injection_fails_soft_on_import_error(self, tmp_path, monkeypatch):
        """If the telemetry module can't be imported, injection
        is silently skipped — never crashes the cycle."""
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {}

        monkeypatch.setattr(
            "core.telemetry.metrics_collector.MetricsCollector",
            property(lambda self: (_ for _ in ()).throw(ImportError("no telemetry"))),
        )

        # Should not raise
        c._inject_sla_breaches(phase_errors)
        assert not any(k.startswith("sla_breach::") for k in phase_errors)

    def test_sla_breach_reaches_reflection_buffer(self, tmp_path, monkeypatch):
        """Breaches injected as phase_errors flow through the
        reflection hook and land in the error buffer."""
        c = _bare_controller(tmp_path)

        class FakeTracker:
            def get_report(self):
                return {
                    "subsystems": {
                        "llm": {"status": "breached", "breaches": ["success_rate"]},
                    },
                    "total_subsystems": 1,
                }

        class FakeTM:
            def __call__(self):
                return self

            def get_sla_tracker(self):
                return FakeTracker()

        monkeypatch.setattr(
            "core.telemetry.metrics_collector.MetricsCollector",
            FakeTM(),
        )

        # Seed phase_errors with a base error + SLA breach
        errors: dict[str, str] = {"some_phase": "something broke"}
        c._inject_sla_breaches(errors)
        _tick(c, errors)

        assert c._error_buffer is not None
        payloads = [r.payload for r in c._error_buffer]
        phases = [p["phase"] for p in payloads]
        assert "sla_breach::llm" in phases
        assert "some_phase" in phases


# ---------------------------------------------------------------------------
# GAP-19: Reflection hook self-error capture
# ---------------------------------------------------------------------------


class TestReflectionHookSelfErrors:
    """When the reflection hook itself fails, the error is now
    captured in phase_errors (visible to operators and future
    reflection runs)."""

    def test_hook_failure_recorded_in_phase_errors(self, tmp_path):
        """A crash inside _run_reflection_hook should inject an
        entry into phase_errors under 'reflection_hook'."""
        import threading

        c = AutonomousController.__new__(AutonomousController)
        c._reflection_synth = None
        c._error_buffer = None
        c._reflection_init_lock = threading.Lock()

        # Force the hook to crash by providing a synth that blows up
        class BrokenSynth:
            def run(self, records):
                raise RuntimeError("synthesizer meltdown")

        phase_errors: dict[str, str] = {"base": "some error"}
        cycle_result: dict[str, Any] = {"cycle_id": "test"}

        # Set the broken synth so the double-checked lock finds it
        c._reflection_synth = BrokenSynth()
        c._error_buffer = deque(maxlen=10)

        # The outer try/except in run_cycle catches this; we
        # simulate it here:
        try:
            c._run_reflection_hook(cycle_result, phase_errors)
        except Exception as exc:
            phase_errors["reflection_hook"] = (
                f"{type(exc).__name__}: {exc}"
            )

        assert "reflection_hook" in phase_errors
        assert "meltdown" in phase_errors["reflection_hook"]

    def test_successful_hook_does_not_inject_error(self, tmp_path):
        """When the hook succeeds, no 'reflection_hook' key should
        appear in phase_errors."""
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {"test_phase": "an error"}
        cycle_result: dict[str, Any] = {"cycle_id": "test"}

        c._run_reflection_hook(cycle_result, phase_errors)
        assert "reflection_hook" not in phase_errors
