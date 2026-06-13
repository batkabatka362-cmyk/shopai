"""Tests for engines._pattern_av_audit (Wave 823)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.payload_discoverer import (
    DiscoveryResult, _DISCOVERERS, register_discoverer,
)
from engines._pattern_av_audit import (
    PatternAVReport,
    PatternAVViolation,
    run_pattern_av_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        # On the clean branch (post W821), shipping_alert is
        # the only registered discoverer; substrate; clean.
        r = run_pattern_av_audit()
        assert not r.has_violations
        assert "shipping_alert" in r.clean_pairings

    def test_substrate_domains_count(self):
        r = run_pattern_av_audit()
        assert len(r.substrate_domains) == 8

    def test_engine_domains_count(self):
        r = run_pattern_av_audit()
        assert len(r.engine_domains) == 2

    def test_substrate_without_discoverer_reports(self):
        # 8 substrate - 8 registered (all of them) = 0 still
        # needing a discoverer. Coverage achieved W832.
        r = run_pattern_av_audit()
        assert (
            len(r.substrate_without_discoverer) == 0
        )
        assert "shipping_alert" not in (
            r.substrate_without_discoverer
        )


class TestSyntheticDrift:

    def test_engine_mode_registration_flags(self):
        # Register a discoverer for "marketing" (engine-mode)
        # -> Pattern AV should flag.
        snapshot = dict(_DISCOVERERS)
        try:
            register_discoverer(
                "marketing",
                lambda: DiscoveryResult(domain="marketing"),
            )
            r = run_pattern_av_audit()
            assert r.has_violations
            msgs = [
                v.reason for v in r.violations
                if v.domain == "marketing"
            ]
            assert any(
                "engine-mode" in m for m in msgs
            ), msgs
        finally:
            _DISCOVERERS.clear()
            _DISCOVERERS.update(snapshot)

    def test_unknown_domain_registration_flags(self):
        # Bypass the register_discoverer guard by mutating the
        # registry directly (simulates an internal drift bug).
        snapshot = dict(_DISCOVERERS)
        try:
            _DISCOVERERS["totally_made_up_domain"] = (
                lambda: DiscoveryResult(
                    domain="totally_made_up_domain",
                )
            )
            r = run_pattern_av_audit()
            assert r.has_violations
            msgs = [
                v.reason for v in r.violations
                if v.domain == "totally_made_up_domain"
            ]
            assert any(
                "unknown domain" in m for m in msgs
            ), msgs
        finally:
            _DISCOVERERS.clear()
            _DISCOVERERS.update(snapshot)


class TestReportDataclass:

    def test_empty_report_no_violations(self):
        r = PatternAVReport()
        assert not r.has_violations

    def test_report_with_violations(self):
        r = PatternAVReport()
        r.violations.append(PatternAVViolation(
            domain="x", reason="broken",
        ))
        assert r.has_violations
