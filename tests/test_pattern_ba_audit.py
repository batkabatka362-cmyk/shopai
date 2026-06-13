"""Tests for engines._pattern_ba_audit (Wave 852)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engines._pattern_ba_audit import (
    PatternBAReport,
    PatternBAViolation,
    _scan_autonomy_kinds_set,
    _expected_kinds,
    run_pattern_ba_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_ba_audit()
        assert not r.has_violations, [
            (v.expected, v.reason) for v in r.violations
        ]

    def test_expected_kinds_present(self):
        r = run_pattern_ba_audit()
        # 10 domains x 2 kinds. Meta-rollup alerts
        # (autonomy_thrash etc) are intentionally excluded
        # per W937 audit reversal -- they're distinct signal
        # classes not per-domain alerts.
        assert len(r.expected_kinds) == 20
        assert "refund_paused" in r.expected_kinds
        assert "shipping_alert_health_critical" in (
            r.expected_kinds
        )

    def test_thrash_alerts_intentionally_excluded(self):
        """W937 audit decision: meta-alerts stay separate
        from the coalesce path. Operators want to see thrash
        signal alongside, not buried inside, autonomy_degraded."""
        r = run_pattern_ba_audit()
        assert "autonomy_thrash" not in r.expected_kinds
        assert (
            "autonomy_thrash_elevated"
            not in r.expected_kinds
        )


class TestExpectedKinds:

    def test_includes_aliases(self):
        kinds = _expected_kinds()
        # customer_support -> "refund" alias
        assert "refund_paused" in kinds
        assert "refund_health_critical" in kinds
        # marketing -> "budget" alias
        assert "budget_paused" in kinds

    def test_substrate_domains_use_canonical_names(self):
        kinds = _expected_kinds()
        assert "shipping_alert_paused" in kinds
        assert "shipping_alert_health_critical" in kinds


class TestScanAutonomyKindsSet:

    def test_scan_real_notify(self):
        result = _scan_autonomy_kinds_set(
            Path("engines/_notify.py"),
        )
        assert result is not None
        assert "refund_paused" in result

    def test_missing_file_returns_none(self, tmp_path):
        result = _scan_autonomy_kinds_set(
            tmp_path / "nope.py",
        )
        assert result is None

    def test_file_without_set_returns_none(self, tmp_path):
        f = tmp_path / "fake.py"
        f.write_text(
            "x = 1\nother_set = {'a', 'b'}\n",
            encoding="utf-8",
        )
        assert _scan_autonomy_kinds_set(f) is None

    def test_finds_literal_set(self, tmp_path):
        f = tmp_path / "fake.py"
        f.write_text(
            "def collect_alerts():\n"
            "    autonomy_kinds = {'a', 'b', 'c'}\n",
            encoding="utf-8",
        )
        # _scan_autonomy_kinds_set walks tree, finds the
        # assignment regardless of nesting
        assert _scan_autonomy_kinds_set(f) == {"a", "b", "c"}


class TestSyntheticDrift:

    def test_synthetic_missing_kind_flagged(self, tmp_path):
        # Build a notify file with an incomplete kinds set.
        eng = tmp_path / "engines"
        eng.mkdir()
        notify = eng / "_notify.py"
        notify.write_text(
            "def collect_alerts():\n"
            "    autonomy_kinds = {'refund_paused'}\n",
            encoding="utf-8",
        )
        r = run_pattern_ba_audit(repo_root=tmp_path)
        assert r.has_violations
        # Many missing kinds (all but refund_paused)
        assert "shipping_alert_paused" in (
            r.missing_in_catalog
        )

    def test_synthetic_extra_kind_flagged(self, tmp_path):
        eng = tmp_path / "engines"
        eng.mkdir()
        notify = eng / "_notify.py"
        all_expected = _expected_kinds()
        all_expected.add("nonexistent_domain_paused")
        literal = ", ".join(
            f"'{k}'" for k in sorted(all_expected)
        )
        notify.write_text(
            "def collect_alerts():\n"
            f"    autonomy_kinds = {{{literal}}}\n",
            encoding="utf-8",
        )
        r = run_pattern_ba_audit(repo_root=tmp_path)
        assert r.has_violations
        assert "nonexistent_domain_paused" in (
            r.extra_in_catalog
        )

    def test_missing_notify_flagged(self, tmp_path):
        r = run_pattern_ba_audit(repo_root=tmp_path)
        assert r.has_violations
        assert any(
            "not found" in v.reason for v in r.violations
        )


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBAReport().has_violations

    def test_with_violations(self):
        r = PatternBAReport()
        r.violations.append(PatternBAViolation(
            expected="x", reason="missing",
        ))
        assert r.has_violations
