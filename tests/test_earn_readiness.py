"""Tests for engines.earn_readiness -- W963-108."""
from __future__ import annotations

from unittest.mock import patch

from engines.earn_readiness import EarnReadinessEngine
from engines.earn_readiness.composer import (
    CheckSlice,
    EarnReadinessReport,
    _compose_next_action,
    _compose_verdict,
    build_readiness,
)


# ── _compose_verdict ──────────────────────────────────────


class TestComposeVerdict:
    def test_all_ok_returns_ready(self):
        checks = [
            CheckSlice("a", "ok", "fine"),
            CheckSlice("b", "ok", "fine"),
        ]
        assert _compose_verdict(checks) == "ready"

    def test_any_fail_returns_not_ready(self):
        checks = [
            CheckSlice("a", "ok", "fine"),
            CheckSlice("b", "fail", "broken"),
            CheckSlice("c", "warn", "iffy"),
        ]
        assert _compose_verdict(checks) == "not_ready"

    def test_warn_only_returns_warn(self):
        checks = [
            CheckSlice("a", "ok", "fine"),
            CheckSlice("b", "warn", "iffy"),
        ]
        assert _compose_verdict(checks) == "warn"

    def test_empty_returns_ready(self):
        assert _compose_verdict([]) == "ready"


# ── _compose_next_action ──────────────────────────────────


class TestComposeNextAction:
    def test_ready_suggests_cycle_run(self):
        action = _compose_next_action("ready", [])
        assert "cycle run" in action

    def test_blocker_first_in_warn(self):
        """When ready=warn, next_action should be the first
        warning's fix."""
        checks = [
            CheckSlice("a", "ok", "fine"),
            CheckSlice(
                "b", "warn", "iffy", fix="shopai go-live",
            ),
        ]
        action = _compose_next_action("warn", checks)
        assert "go-live" in action

    def test_failure_outranks_warning(self):
        """fail severity > warn; next_action surfaces the
        fail's fix even when warns are present too."""
        checks = [
            CheckSlice(
                "a", "warn", "x", fix="shopai a-fix",
            ),
            CheckSlice(
                "b", "fail", "x", fix="shopai b-fix",
            ),
            CheckSlice(
                "c", "warn", "x", fix="shopai c-fix",
            ),
        ]
        action = _compose_next_action("not_ready", checks)
        assert "b-fix" in action


# ── build_readiness ───────────────────────────────────────


class TestBuildReadiness:
    """End-to-end build with mocked probes."""

    def test_all_probes_passing_returns_ready(self):
        with patch(
            "engines.earn_readiness.composer."
            "_check_api_inventory",
            return_value=CheckSlice("api_inventory", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_go_live",
            return_value=CheckSlice("go_live", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_autonomy_doctor",
            return_value=CheckSlice("autonomy_doctor", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_cycle_history",
            return_value=CheckSlice("cycle_history", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_wired_engines",
            return_value=CheckSlice("wired_engines", "ok", "x"),
        ):
            report = build_readiness()
        assert report.overall_verdict == "ready"
        assert report.ok_count == 5
        assert report.fail_count == 0
        assert "READY TO LAUNCH" in report.headline

    def test_one_fail_blocks_launch(self):
        with patch(
            "engines.earn_readiness.composer."
            "_check_api_inventory",
            return_value=CheckSlice(
                "api_inventory", "fail",
                "no brain", fix="shopai api-status",
            ),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_go_live",
            return_value=CheckSlice("go_live", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_autonomy_doctor",
            return_value=CheckSlice("autonomy_doctor", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_cycle_history",
            return_value=CheckSlice(
                "cycle_history", "fail",
                "no cycle", fix="shopai cycle run --yes",
            ),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_wired_engines",
            return_value=CheckSlice("wired_engines", "ok", "x"),
        ):
            report = build_readiness()
        assert report.overall_verdict == "not_ready"
        assert report.fail_count == 2
        assert "NOT READY" in report.headline
        # top_blockers populated
        names = [c.name for c in report.top_blockers]
        assert "api_inventory" in names
        assert "cycle_history" in names

    def test_warn_only_yields_warn_verdict(self):
        with patch(
            "engines.earn_readiness.composer."
            "_check_api_inventory",
            return_value=CheckSlice("api_inventory", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_go_live",
            return_value=CheckSlice(
                "go_live", "warn", "minor",
            ),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_autonomy_doctor",
            return_value=CheckSlice("autonomy_doctor", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_cycle_history",
            return_value=CheckSlice("cycle_history", "ok", "x"),
        ), patch(
            "engines.earn_readiness.composer."
            "_check_wired_engines",
            return_value=CheckSlice("wired_engines", "ok", "x"),
        ):
            report = build_readiness()
        assert report.overall_verdict == "warn"
        assert report.warn_count == 1
        assert "WARNINGS" in report.headline.upper()

    def test_probe_exception_marks_warn_not_crash(self):
        """If an individual probe raises, the slice is
        marked warn so the composer downgrades gracefully
        instead of crashing."""
        # Mock each underlying probe by raising in one of
        # them. The probes catch their own exceptions and
        # return warn slices.
        from engines._go_live_check import run_go_live_check
        with patch(
            "engines._go_live_check.run_go_live_check",
            side_effect=RuntimeError("test crash"),
        ):
            # Even with go_live probe broken, build_readiness
            # should complete -- just produces a warn slice
            # for go_live, doesn't propagate the exception.
            report = build_readiness()
        go_live_slice = next(
            (c for c in report.checks if c.name == "go_live"),
            None,
        )
        assert go_live_slice is not None
        # Probe failure surfaces as warn
        assert go_live_slice.cls == "warn"


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = EarnReadinessEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self):
        r = EarnReadinessEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = EarnReadinessEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = EarnReadinessEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = EarnReadinessEngine().run({})
        assert r["meta"]["engine"] == "earn_readiness"

    def test_data_has_checks(self):
        r = EarnReadinessEngine().run({})
        assert "checks" in r["data"]
        assert isinstance(r["data"]["checks"], list)
        assert len(r["data"]["checks"]) >= 4

    def test_data_has_verdict(self):
        r = EarnReadinessEngine().run({})
        assert r["data"]["overall_verdict"] in (
            "ready", "warn", "not_ready",
        )

    def test_data_has_headline_and_next_action(self):
        r = EarnReadinessEngine().run({})
        assert r["data"]["headline"]
        assert r["data"]["next_action"]

    def test_data_has_counts(self):
        r = EarnReadinessEngine().run({})
        d = r["data"]
        assert "ok_count" in d
        assert "warn_count" in d
        assert "fail_count" in d
        total = (
            d["ok_count"] + d["warn_count"] + d["fail_count"]
        )
        assert total == len(d["checks"])
