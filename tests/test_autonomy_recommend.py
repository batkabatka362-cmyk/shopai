"""Tests for core.automation.autonomy_recommend (Wave 716-720).

Recommendation engine that aggregates 5 signal sources into a
priority-ranked operator action list.
"""
from __future__ import annotations

from core.automation.autonomy_recommend import (
    Recommendation,
    RecommendReport,
    _domain_hyphen,
    run_autonomy_recommend,
)


class TestDomainHyphen:

    def test_customer_support_alias(self):
        assert _domain_hyphen("customer_support") == "refund"

    def test_marketing_alias(self):
        assert _domain_hyphen("marketing") == "marketing"

    def test_passthrough_with_hyphen_conversion(self):
        assert _domain_hyphen("catalog_quality") == (
            "catalog-quality"
        )


class TestRunAutonomyRecommend:

    def test_returns_report(self):
        r = run_autonomy_recommend()
        assert isinstance(r, RecommendReport)

    def test_idle_branch_yields_only_info(self):
        # On the clean branch, no domains are paused / degraded
        # / wiring-fail / dormant -- only INFO recs for untuned
        # env knobs should fire.
        r = run_autonomy_recommend()
        assert r.critical_count == 0
        assert r.warn_count == 0
        # 10 domains, all quiet with default env -> 10 info
        assert r.info_count == 10
        for rec in r.recommendations:
            assert rec.severity == "info"
            assert rec.priority == 20

    def test_window_hours_preserved(self):
        r = run_autonomy_recommend(window_hours=48.0)
        assert r.window_hours == 48.0

    def test_recommendations_sorted_by_priority_desc(self):
        r = run_autonomy_recommend()
        priorities = [
            rec.priority for rec in r.recommendations
        ]
        assert priorities == sorted(priorities, reverse=True)

    def test_each_rec_has_command(self):
        r = run_autonomy_recommend()
        for rec in r.recommendations:
            assert rec.command  # non-empty
            assert "shopai" in rec.command


class TestRecommendReportCounts:

    def test_empty_counts_zero(self):
        r = RecommendReport()
        assert r.critical_count == 0
        assert r.warn_count == 0
        assert r.info_count == 0

    def test_mixed_severity_counts(self):
        r = RecommendReport()
        r.recommendations = [
            Recommendation(
                domain="a", action="x", command="y",
                severity="critical",
            ),
            Recommendation(
                domain="b", action="x", command="y",
                severity="critical",
            ),
            Recommendation(
                domain="c", action="x", command="y",
                severity="warn",
            ),
            Recommendation(
                domain="d", action="x", command="y",
                severity="info",
            ),
        ]
        assert r.critical_count == 2
        assert r.warn_count == 1
        assert r.info_count == 1


class TestRecommendationDataclass:

    def test_defaults(self):
        r = Recommendation(
            domain="x", action="y", command="z",
        )
        assert r.severity == "info"
        assert r.priority == 0
        assert r.reason == ""
