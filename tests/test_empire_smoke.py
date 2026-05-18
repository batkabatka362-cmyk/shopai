"""Tests for ``scripts/empire_smoke.py``.

The smoke script itself runs the full empire-AGI surface
read-only and reports pass/empty/fail per step. These tests
verify the script's step-level decision-making (what counts
as PASS vs EMPTY vs FAIL) on synthetic inputs.

End-to-end smoke verification against real wiring lives in
``scripts/empire_smoke.py`` directly -- it's a script, not a
pytest fixture, and operators run it as ``python scripts/...``.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_smoke():
    """Load the script as a regular module despite its
    top-level path-mangling."""
    spec = importlib.util.spec_from_file_location(
        "empire_smoke", "scripts/empire_smoke.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def smoke():
    return _load_smoke()


# ─── StepResult shape ────────────────────────────────────────


class TestStepResult:

    def test_status_values_canonical(self, smoke):
        """Every step should return PASS / EMPTY / FAIL --
        the operator-facing report depends on these three."""
        r = smoke.StepResult(name="t", status="PASS")
        assert r.status in {"PASS", "EMPTY", "FAIL"}
        assert r.detail == ""
        assert r.error is None


# ─── Step: narrative parsers ─────────────────────────────────


class TestNarrativeParsersStep:

    def test_passes_when_format_module_imports(self, smoke):
        result = smoke._step_narrative_parsers()
        assert result.status == "PASS"
        assert "round-trip" in result.detail.lower()


# ─── Step: guardrail roster ──────────────────────────────────


class TestGuardrailRosterStep:

    def test_passes_when_roster_present(self, smoke, monkeypatch):
        # Clear env vars so all engines are reported as disabled.
        from engines._agi_context import GUARDRAIL_ENGINES
        for engine in GUARDRAIL_ENGINES:
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        result = smoke._step_guardrail_roster()
        assert result.status == "PASS"
        assert "0 currently enabled" in result.detail


# ─── Step: transfer-suggest pipeline ─────────────────────────


class TestTransferSuggestStep:

    def test_empty_pipeline_returns_empty(self, smoke):
        """Fresh install: queue has no rows → EMPTY, not FAIL."""
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = []
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            result = smoke._step_transfer_suggest_pipeline(None)
        assert result.status == "EMPTY"

    def test_typeerror_on_store_id_kwarg_flagged_as_fail(
        self, smoke,
    ):
        """Pre-#239 queue without ``store_id`` support is a
        critical wiring break -- empire-AGI doesn't work
        without it."""
        fake_queue = MagicMock()
        fake_queue.list_by_status.side_effect = TypeError(
            "unexpected keyword argument 'store_id'",
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            result = smoke._step_transfer_suggest_pipeline("store-a")
        assert result.status == "FAIL"
        assert "PR #239" in result.detail


# ─── Step: engine alerts ─────────────────────────────────────


class TestEngineAlertsStep:

    def test_empty_alerts_returns_empty(self, smoke):
        with patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[],
        ):
            result = smoke._step_engine_alerts()
        assert result.status == "EMPTY"
        assert "0 engine" in result.detail

    def test_alerts_present_returns_pass(self, smoke):
        from core.approval.outcome_trends import EngineAlert

        fake = EngineAlert(
            engine="loyalty",
            recent_executed=5, baseline_executed=20,
            recent_score=0.2, baseline_score=0.85,
            recent_polarised=5, baseline_polarised=18,
            drop=0.65, detail="degraded",
            kind="outcome_score_degraded",
        )
        with patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[fake],
        ):
            result = smoke._step_engine_alerts()
        assert result.status == "PASS"

    def test_compute_raise_returns_fail(self, smoke):
        with patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            side_effect=RuntimeError("module unwired"),
        ):
            result = smoke._step_engine_alerts()
        assert result.status == "FAIL"
        assert "module unwired" in (result.error or "")


# ─── Step: transfer credit ───────────────────────────────────


class TestTransferCreditStep:

    def test_empty_credit_returns_empty(self, smoke):
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=[],
        ):
            result = smoke._step_transfer_credit()
        assert result.status == "EMPTY"

    def test_compute_raise_returns_fail(self, smoke):
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            side_effect=RuntimeError("attribution broken"),
        ):
            result = smoke._step_transfer_credit()
        assert result.status == "FAIL"


# ─── main() exit code ────────────────────────────────────────


class TestMainExitCode:

    def test_exit_zero_when_no_failures(self, smoke):
        """All steps pass / empty → exit 0."""
        with patch.object(
            smoke, "_STEPS",
            [
                ("t1", lambda: smoke.StepResult("t1", "PASS")),
                ("t2", lambda: smoke.StepResult("t2", "EMPTY")),
            ],
        ), patch.object(sys, "argv", ["empire_smoke.py", "--json"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = smoke.main()
        assert code == 0
        data = json.loads(buf.getvalue())
        assert data["all_green"] is True
        assert data["failed"] == 0

    def test_exit_one_when_any_failure(self, smoke):
        with patch.object(
            smoke, "_STEPS",
            [
                ("t1", lambda: smoke.StepResult("t1", "PASS")),
                ("t2", lambda: smoke.StepResult("t2", "FAIL")),
            ],
        ), patch.object(sys, "argv", ["empire_smoke.py", "--json"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = smoke.main()
        assert code == 1
        data = json.loads(buf.getvalue())
        assert data["all_green"] is False
        assert data["failed"] == 1
