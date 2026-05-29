"""Tests for engines._pattern_au_audit (Wave 819)."""
from __future__ import annotations

from unittest.mock import patch

from engines._pattern_au_audit import (
    PatternAUReport,
    PatternAUViolation,
    run_pattern_au_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        # Post-W815/W816, autonomy_fire + autonomy_armed are in
        # parity (10 domains each) + every applier resolves.
        r = run_pattern_au_audit()
        assert not r.has_violations, [
            (v.domain, v.reason) for v in r.violations
        ]
        assert len(r.clean_domains) == 10

    def test_catalogs_have_same_size(self):
        r = run_pattern_au_audit()
        assert len(r.domains_in_fire_catalog) == 10
        assert len(r.domains_in_armed_catalog) == 10

    def test_shipping_alert_in_both(self):
        r = run_pattern_au_audit()
        assert "shipping_alert" in r.domains_in_fire_catalog
        assert "shipping_alert" in r.domains_in_armed_catalog


class TestSyntheticDrift:

    def test_fire_missing_a_domain_flags(self):
        # Strip "shipping_alert" from autonomy_fire catalog ->
        # audit should flag that domain as missing in fire.
        from core.automation import autonomy_fire as _af
        broken_appliers = {
            k: v for k, v in _af._DOMAIN_APPLIERS.items()
            if k != "shipping_alert"
        }
        with patch.dict(
            _af._DOMAIN_APPLIERS,
            broken_appliers, clear=True,
        ):
            r = run_pattern_au_audit()
        assert r.has_violations
        reasons = " ".join(v.reason for v in r.violations)
        assert "shipping_alert" in " ".join(
            v.domain for v in r.violations
        )
        assert "NOT in autonomy_fire" in reasons

    def test_armed_missing_a_domain_flags(self):
        # Strip "marketing" from autonomy_armed.DOMAIN_APPLY_FLAGS
        # -> audit should flag missing in armed.
        from core.automation import autonomy_armed as _aa
        broken_flags = {
            k: v for k, v in _aa.DOMAIN_APPLY_FLAGS.items()
            if k != "marketing"
        }
        with patch.dict(
            _aa.DOMAIN_APPLY_FLAGS,
            broken_flags, clear=True,
        ):
            r = run_pattern_au_audit()
        assert r.has_violations
        reasons = " ".join(v.reason for v in r.violations)
        assert "NOT in autonomy_armed" in reasons

    def test_broken_applier_function_name_flags(self):
        from core.automation import autonomy_fire as _af
        broken_appliers = dict(_af._DOMAIN_APPLIERS)
        broken_appliers["shipping_alert"] = (
            "engines.shipping_alert_autonomy.shipping_applier",
            "totally_made_up_function_name",
        )
        with patch.dict(
            _af._DOMAIN_APPLIERS,
            broken_appliers, clear=True,
        ):
            r = run_pattern_au_audit()
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any(
            "no callable" in m for m in msgs
        ), msgs


class TestReportDataclass:

    def test_empty_report_no_violations(self):
        r = PatternAUReport()
        assert not r.has_violations

    def test_report_with_violations(self):
        r = PatternAUReport()
        r.violations.append(PatternAUViolation(
            domain="x", reason="broken",
        ))
        assert r.has_violations
