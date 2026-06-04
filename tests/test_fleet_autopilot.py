"""Tests for engines.fleet_autopilot — W963-26."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.fleet_autopilot import FleetAutopilotEngine
from engines.fleet_autopilot.runner import (
    StoreOutcome,
    _compute_overall,
    run_fleet_autopilot,
)


# ── _compute_overall ──────────────────────────────────────


class TestComputeOverall:
    def test_empty_fleet_skipped(self):
        assert _compute_overall([]) == "skipped"

    def test_all_ok(self):
        outs = [
            StoreOutcome(store_id="a", verdict="ok"),
            StoreOutcome(store_id="b", verdict="ok"),
        ]
        assert _compute_overall(outs) == "ok"

    def test_one_error_dominates(self):
        outs = [
            StoreOutcome(store_id="a", verdict="ok"),
            StoreOutcome(store_id="b", verdict="error"),
        ]
        assert _compute_overall(outs) == "error"

    def test_warn_over_ok(self):
        outs = [
            StoreOutcome(store_id="a", verdict="ok"),
            StoreOutcome(store_id="b", verdict="warn"),
        ]
        assert _compute_overall(outs) == "warn"

    def test_severity_order(self):
        # error > warn > ok > disabled > skipped
        outs = [
            StoreOutcome(store_id="a", verdict="warn"),
            StoreOutcome(store_id="b", verdict="error"),
            StoreOutcome(store_id="c", verdict="ok"),
        ]
        assert _compute_overall(outs) == "error"


# ── run_fleet_autopilot ───────────────────────────────────


class TestRunFleet:
    def test_no_stores(self):
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=[],
        ):
            r = run_fleet_autopilot(confirmed=False)
        assert r.total_stores == 0
        assert r.by_store == []
        assert r.overall_verdict == "skipped"

    def test_iterates_all_stores(self):
        fake_ap_report = MagicMock()
        fake_ap_report.overall_verdict = "ok"
        fake_ap_report.stages = []
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.autopilot.runner.run_autopilot",
            return_value=fake_ap_report,
        ):
            r = run_fleet_autopilot(confirmed=False)
        assert r.total_stores == 3
        assert len(r.by_store) == 3
        assert {o.store_id for o in r.by_store} == {
            "s1", "s2", "s3",
        }

    def test_only_store_short_circuits_listing(self):
        fake_ap_report = MagicMock()
        fake_ap_report.overall_verdict = "ok"
        fake_ap_report.stages = []
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=["s1", "s2", "s3"],
        ) as list_mock, patch(
            "engines.autopilot.runner.run_autopilot",
            return_value=fake_ap_report,
        ):
            r = run_fleet_autopilot(
                confirmed=False, only_store="s2",
            )
        # only_store skips fleet listing entirely
        assert not list_mock.called
        assert r.total_stores == 1
        assert r.by_store[0].store_id == "s2"

    def test_skip_stores_excluded(self):
        fake_ap_report = MagicMock()
        fake_ap_report.overall_verdict = "ok"
        fake_ap_report.stages = []
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.autopilot.runner.run_autopilot",
            return_value=fake_ap_report,
        ):
            r = run_fleet_autopilot(
                confirmed=False,
                skip_stores=["s2"],
            )
        assert len(r.by_store) == 2
        assert "s2" in r.skipped_stores

    def test_single_store_exception_does_not_halt_fleet(self):
        fake_ok = MagicMock()
        fake_ok.overall_verdict = "ok"
        fake_ok.stages = []
        call_count = {"n": 0}
        def _run(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("store 2 broke")
            return fake_ok
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.autopilot.runner.run_autopilot",
            side_effect=_run,
        ):
            r = run_fleet_autopilot(confirmed=False)
        # All 3 stores still appear in the report
        assert len(r.by_store) == 3
        # s2 marked error
        s2 = [
            o for o in r.by_store if o.store_id == "s2"
        ][0]
        assert s2.verdict == "error"
        assert s2.error_count >= 1


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetAutopilotEngine().run({})
        assert r["status"] == "success"
        assert "by_store" in r["data"]

    def test_none_success(self):
        r = FleetAutopilotEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetAutopilotEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetAutopilotEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetAutopilotEngine().run({})
        assert r["meta"]["engine"] == "fleet_autopilot"


class TestEngineActions:
    def test_dry_run_default(self):
        r = FleetAutopilotEngine().run({})
        assert r["data"]["confirmed"] is False

    def test_skip_stores_non_list_falls_back(self):
        r = FleetAutopilotEngine().run({
            "data": {"skip_stores": "not-a-list"},
        })
        assert r["data"]["skipped_stores"] == []

    def test_only_store_threaded(self):
        with patch(
            "engines.fleet_autopilot.runner._run_one_store",
            return_value=StoreOutcome(
                store_id="x", verdict="ok",
            ),
        ):
            r = FleetAutopilotEngine().run({
                "data": {"only_store": "x"},
            })
        assert r["data"]["only_store"] == "x"
        assert r["data"]["total_stores"] == 1

    def test_overall_verdict_present(self):
        r = FleetAutopilotEngine().run({})
        assert r["data"]["overall_verdict"] in {
            "ok", "warn", "error", "disabled", "skipped",
        }


# ── Next action ────────────────────────────────────────────


class TestNextAction:
    def test_no_stores_drills_onboard(self):
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=[],
        ):
            r = FleetAutopilotEngine().run({})
        assert "onboard" in r["data"]["next_action"]

    def test_dry_run_drills_yes(self):
        fake_ap_report = MagicMock()
        fake_ap_report.overall_verdict = "warn"
        fake_ap_report.stages = []
        with patch(
            "engines.fleet_autopilot.runner._list_fleet",
            return_value=["s1"],
        ), patch(
            "engines.autopilot.runner.run_autopilot",
            return_value=fake_ap_report,
        ):
            r = FleetAutopilotEngine().run({})
        assert "Dry-run" in r["data"]["next_action"]
