"""Tests for engines._pattern_t_audit (Wave 185-186)."""
from __future__ import annotations

from engines._pattern_t_audit import (
    EnvKnob,
    PatternTReport,
    _DOMAINS,
    _expand_knobs,
    build_autonomy_env_registry,
    run_pattern_t_audit,
)


class TestExpandKnobs:

    def test_standard_health_knobs_emit_5_entries(self):
        knobs = _expand_knobs("TESTPREFIX", [])
        # 5 standard health knobs
        assert len(knobs) == 5
        assert (
            "SHOPAI_AUTO_PAUSE_TESTPREFIX_ON_FAILURE" in knobs
        )
        assert (
            "SHOPAI_TESTPREFIX_HEALTH_MIN_SAMPLE" in knobs
        )

    def test_extras_appended(self):
        knobs = _expand_knobs(
            "FOO", ["SHOPAI_FOO_CUSTOM"],
        )
        assert "SHOPAI_FOO_CUSTOM" in knobs
        assert len(knobs) == 6


class TestRegistry:

    def test_all_6_domains_scanned(self):
        report = build_autonomy_env_registry()
        assert len(report.domains_scanned) == 6

    def test_total_knob_count(self):
        report = build_autonomy_env_registry()
        # 6 domains × 5 standard + extras
        # customer_support_refund: 5 + 2 = 7
        # marketing_budget: 5 + 1 = 6
        # fulfillment: 5
        # inventory: 5 + 2 = 7
        # discount_cleanup: 5 + 2 = 7
        # order_followup: 5
        # Total: 37
        assert report.total_knobs == 37

    def test_unset_knob_records_none_value(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_REFUND_MAX_AMOUNT_USD", raising=False,
        )
        report = build_autonomy_env_registry()
        target = next(
            k for k in report.knobs
            if k.name == "SHOPAI_REFUND_MAX_AMOUNT_USD"
        )
        assert target.current_value is None

    def test_set_knob_recorded(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_REFUND_MAX_AMOUNT_USD", "1000",
        )
        report = build_autonomy_env_registry()
        target = next(
            k for k in report.knobs
            if k.name == "SHOPAI_REFUND_MAX_AMOUNT_USD"
        )
        assert target.current_value == "1000"
        assert target in report.set_knobs


class TestDomainCatalog:

    def test_known_domains_present(self):
        names = set(_DOMAINS.keys())
        assert names == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
        }


class TestRunPatternTAudit:

    def test_returns_report(self):
        report = run_pattern_t_audit()
        assert isinstance(report, PatternTReport)


class TestEnvKnobDataclass:

    def test_default(self):
        k = EnvKnob(name="X", domain="d")
        assert k.current_value is None
