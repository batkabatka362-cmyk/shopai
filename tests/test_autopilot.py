"""Tests for engines.autopilot — W963-23."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.autopilot import AutopilotEngine
from engines.autopilot.runner import (
    AutopilotReport,
    StageResult,
    _compute_overall,
    _env_gate,
    run_autopilot,
)


# ── _env_gate ──────────────────────────────────────────────


class TestEnvGate:
    def test_unset_uses_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAKE_KEY_X", None)
            assert _env_gate("FAKE_KEY_X", True) is True
            assert _env_gate("FAKE_KEY_X", False) is False

    def test_truthy_values_enable(self):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            with patch.dict(
                os.environ, {"FAKE_KEY_X": raw}, clear=False,
            ):
                assert _env_gate("FAKE_KEY_X", False) is True

    def test_falsy_values_disable(self):
        for raw in ("0", "false", "no", "off", "anything"):
            with patch.dict(
                os.environ, {"FAKE_KEY_X": raw}, clear=False,
            ):
                assert _env_gate("FAKE_KEY_X", True) is False


# ── _compute_overall ──────────────────────────────────────


class TestComputeOverall:
    def test_all_ok(self):
        stages = [
            StageResult(name="a", enabled=True, verdict="ok"),
            StageResult(name="b", enabled=True, verdict="ok"),
        ]
        assert _compute_overall(stages) == "ok"

    def test_warn_dominates_ok(self):
        stages = [
            StageResult(name="a", enabled=True, verdict="ok"),
            StageResult(
                name="b", enabled=True, verdict="warn",
            ),
        ]
        assert _compute_overall(stages) == "warn"

    def test_error_dominates_warn(self):
        stages = [
            StageResult(
                name="a", enabled=True, verdict="warn",
            ),
            StageResult(
                name="b", enabled=True, verdict="error",
            ),
        ]
        assert _compute_overall(stages) == "error"

    def test_all_disabled(self):
        stages = [
            StageResult(
                name="a", enabled=False, verdict="disabled",
            ),
        ]
        assert _compute_overall(stages) == "disabled"

    def test_empty(self):
        assert _compute_overall([]) == "skipped"


# ── run_autopilot ──────────────────────────────────────────


class TestRunAutopilot:
    def test_unconfirmed_dry_run_all_writers_disabled(
        self, tmp_path,
    ):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "SHOPAI_AUTOPILOT_WELCOME",
                "SHOPAI_AUTOPILOT_REVIEWS",
            ):
                os.environ.pop(k, None)
            r = run_autopilot(
                confirmed=False, store_id=None,
            )
        welcome = [
            s for s in r.stages if s.name == "welcome"
        ][0]
        reviews = [
            s for s in r.stages if s.name == "reviews"
        ][0]
        assert welcome.verdict == "disabled"
        assert reviews.verdict == "disabled"
        assert not welcome.fired
        assert not reviews.fired

    def test_returns_four_stages(self):
        r = run_autopilot(
            confirmed=False, store_id=None,
        )
        names = [s.name for s in r.stages]
        assert names == [
            "welcome", "reviews", "measure", "health",
        ]

    def test_measure_runs_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPAI_AUTOPILOT_MEASURE", None)
            r = run_autopilot(
                confirmed=False, store_id=None,
            )
        measure = [
            s for s in r.stages if s.name == "measure"
        ][0]
        assert measure.enabled is True

    def test_writers_fire_when_env_gates_set_and_confirmed(
        self,
    ):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={}, error="",
        )
        with patch.dict(
            os.environ,
            {
                "SHOPAI_AUTOPILOT_WELCOME": "1",
                "SHOPAI_AUTOPILOT_REVIEWS": "1",
            },
            clear=False,
        ), patch(
            "engines.welcome_series.sender._hydrate_customers",
            return_value=[],
        ), patch(
            "engines.review_request.sender._hydrate_orders",
            return_value=[],
        ), patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            r = run_autopilot(
                confirmed=True, store_id=None,
            )
        welcome = [
            s for s in r.stages if s.name == "welcome"
        ][0]
        reviews = [
            s for s in r.stages if s.name == "reviews"
        ][0]
        assert welcome.fired
        assert reviews.fired


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_success(self):
        r = AutopilotEngine().run({})
        assert r["status"] == "success"
        assert "stages" in r["data"]

    def test_none_input_success(self):
        r = AutopilotEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AutopilotEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AutopilotEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AutopilotEngine().run({})
        assert r["meta"]["engine"] == "autopilot"


class TestEngineActions:
    def test_dry_run_by_default(self):
        r = AutopilotEngine().run({})
        assert r["data"]["confirmed"] is False
        nxt = r["data"]["next_action"]
        assert "Dry-run" in nxt or "preview" in nxt

    def test_store_id_threaded(self):
        r = AutopilotEngine().run({
            "data": {"store_id": "main"},
        })
        assert r["data"]["store_id"] == "main"

    def test_four_stages_present(self):
        r = AutopilotEngine().run({})
        assert len(r["data"]["stages"]) == 4

    def test_overall_verdict_valid(self):
        r = AutopilotEngine().run({})
        assert r["data"]["overall_verdict"] in {
            "ok", "warn", "error", "disabled", "skipped",
        }
