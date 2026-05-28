"""Tests for core.automation.autonomy_summarize (Wave 303-307)."""
from __future__ import annotations

from core.automation.autonomy_summarize import (
    AutonomySummary,
    _classify,
    _render_text,
    run_autonomy_summarize,
)


class TestClassify:

    def test_all_clean(self):
        cls = _classify(
            {"ok": 7, "warn": 0, "fail": 0},
            {"ok": 7, "error": 0},
            {"verdict": "quiet", "paused_domains": []},
        )
        assert cls == "ok"

    def test_doctor_fail(self):
        cls = _classify(
            {"ok": 5, "warn": 0, "fail": 2},
            {"ok": 7, "error": 0},
            {"verdict": "quiet", "paused_domains": []},
        )
        assert cls == "fail"

    def test_smoke_error_is_fail(self):
        cls = _classify(
            {"ok": 7, "warn": 0, "fail": 0},
            {"ok": 5, "error": 2},
            {"verdict": "quiet", "paused_domains": []},
        )
        assert cls == "fail"

    def test_doctor_warn(self):
        cls = _classify(
            {"ok": 5, "warn": 2, "fail": 0},
            {"ok": 7, "error": 0},
            {"verdict": "quiet", "paused_domains": []},
        )
        assert cls == "warn"

    def test_paused_domain(self):
        cls = _classify(
            {"ok": 7, "warn": 0, "fail": 0},
            {"ok": 7, "error": 0},
            {
                "verdict": "paused",
                "paused_domains": ["marketing"],
            },
        )
        assert cls == "warn"

    def test_degraded_verdict(self):
        cls = _classify(
            {"ok": 7, "warn": 0, "fail": 0},
            {"ok": 7, "error": 0},
            {"verdict": "degraded", "paused_domains": []},
        )
        assert cls == "warn"

    def test_fail_overrides_warn(self):
        cls = _classify(
            {"ok": 0, "warn": 0, "fail": 7},
            {"ok": 5, "error": 2},
            {
                "verdict": "paused",
                "paused_domains": ["x"],
            },
        )
        assert cls == "fail"


class TestRenderText:

    def test_ok_text(self):
        text = _render_text(
            cls="ok",
            doctor={"ok": 7, "warn": 0, "fail": 0,
                    "total": 7, "fail_domains": [],
                    "warn_domains": []},
            smoke={"ok": 7, "error": 0, "total": 7,
                   "error_domains": []},
            status={"verdict": "quiet",
                    "applied": 0,
                    "paused_domains": [],
                    "domain_count": 7},
            env={"set": 0, "total": 43},
        )
        assert text.startswith(
            "Autonomy substrate is HEALTHY"
        )
        assert "7 domains" in text
        assert text.endswith(".")
        assert "drill" not in text  # OK case = no drill hint

    def test_warn_text_includes_drill(self):
        text = _render_text(
            cls="warn",
            doctor={"ok": 6, "warn": 1, "fail": 0,
                    "total": 7, "fail_domains": [],
                    "warn_domains": ["marketing"]},
            smoke={"ok": 7, "error": 0, "total": 7,
                   "error_domains": []},
            status={"verdict": "paused",
                    "applied": 0,
                    "paused_domains": ["marketing"],
                    "domain_count": 7},
            env={"set": 2, "total": 43},
        )
        assert "ISSUE" in text
        assert "paused: marketing" in text
        assert "shopai autonomy-doctor" in text

    def test_fail_text_includes_failing_domains(self):
        text = _render_text(
            cls="fail",
            doctor={"ok": 5, "warn": 0, "fail": 2,
                    "total": 7,
                    "fail_domains": ["fulfillment", "inventory"],
                    "warn_domains": []},
            smoke={"ok": 7, "error": 0, "total": 7,
                   "error_domains": []},
            status={"verdict": "quiet",
                    "applied": 0,
                    "paused_domains": [],
                    "domain_count": 7},
            env={"set": 0, "total": 43},
        )
        assert "BROKEN" in text
        assert "FAILING: fulfillment, inventory" in text
        assert "drill" in text


class TestRunAutonomySummarize:

    def test_returns_summary(self):
        r = run_autonomy_summarize()
        assert isinstance(r, AutonomySummary)

    def test_text_non_empty(self):
        r = run_autonomy_summarize()
        assert r.text
        assert r.text.endswith(".")

    def test_overall_cls_valid(self):
        r = run_autonomy_summarize()
        assert r.overall_cls in {"ok", "warn", "fail"}

    def test_has_issues_consistency(self):
        r = run_autonomy_summarize()
        if r.overall_cls == "ok":
            assert not r.has_issues
        else:
            assert r.has_issues

    def test_live_branch_is_healthy(self):
        # Trust anchor: this branch should always render OK
        r = run_autonomy_summarize()
        assert r.overall_cls == "ok", r.text
        assert "HEALTHY" in r.text


class TestDataclass:

    def test_default_summary(self):
        s = AutonomySummary(
            text="x", overall_cls="ok", has_issues=False,
        )
        assert s.text == "x"
        assert not s.has_issues
