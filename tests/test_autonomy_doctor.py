"""Tests for core.automation.autonomy_doctor (Wave 235-237)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.autonomy_doctor import (
    AutonomyDoctorReport,
    DoctorDomainReport,
    _classify,
    _resolve_domain_key,
    run_autonomy_doctor,
)
from core.automation.autonomy_status import DomainSummary


class TestDomainKeyResolver:

    def test_customer_support_aliases_to_refund(self):
        assert _resolve_domain_key("customer_support") == (
            "customer_support_refund"
        )

    def test_marketing_aliases_to_marketing_budget(self):
        assert _resolve_domain_key("marketing") == (
            "marketing_budget"
        )

    def test_other_domains_pass_through(self):
        for d in [
            "fulfillment", "inventory", "discount_cleanup",
            "order_followup", "product_seo",
        ]:
            assert _resolve_domain_key(d) == d


class TestClassify:

    def _summary(self, **kwargs):
        return DomainSummary(
            name=kwargs.get("name", "x"),
            verdict=kwargs.get("verdict", "quiet"),
            paused=kwargs.get("paused", False),
            applied_count=kwargs.get("applied_count", 0),
            health_failure_ratio=kwargs.get(
                "health_failure_ratio", None,
            ),
            next_action=kwargs.get("next_action", ""),
        )

    def _wiring(self, **kwargs):
        return {
            "cycle_hook_wired": kwargs.get(
                "cycle_hook_wired", True,
            ),
            "notify_kinds_count": kwargs.get(
                "notify_kinds_count", 2,
            ),
            "env_gated": kwargs.get("env_gated", True),
            "template_complete": kwargs.get(
                "template_complete", True,
            ),
            "wiring_reasons": kwargs.get(
                "wiring_reasons", [],
            ),
        }

    def test_all_clean_is_ok(self):
        cls, reasons = _classify(
            self._summary(), self._wiring(),
        )
        assert cls == "ok"
        assert reasons == []

    def test_paused_is_warn(self):
        cls, reasons = _classify(
            self._summary(paused=True, next_action="resume"),
            self._wiring(),
        )
        assert cls == "warn"
        assert "paused" in reasons[0]

    def test_degraded_is_warn(self):
        cls, reasons = _classify(
            self._summary(verdict="degraded"),
            self._wiring(),
        )
        assert cls == "warn"

    def test_critical_is_warn(self):
        cls, reasons = _classify(
            self._summary(verdict="critical"),
            self._wiring(),
        )
        assert cls == "warn"

    def test_high_failure_ratio_is_warn(self):
        cls, _ = _classify(
            self._summary(health_failure_ratio=0.30),
            self._wiring(),
        )
        assert cls == "warn"

    def test_missing_cycle_hook_is_fail(self):
        cls, reasons = _classify(
            self._summary(),
            self._wiring(cycle_hook_wired=False),
        )
        assert cls == "fail"
        assert any("cycle hook" in r for r in reasons)

    def test_missing_template_is_fail(self):
        cls, _ = _classify(
            self._summary(),
            self._wiring(template_complete=False),
        )
        assert cls == "fail"

    def test_missing_notify_is_fail(self):
        cls, _ = _classify(
            self._summary(),
            self._wiring(notify_kinds_count=0),
        )
        assert cls == "fail"

    def test_fail_overrides_warn(self):
        cls, _ = _classify(
            self._summary(verdict="degraded"),
            self._wiring(cycle_hook_wired=False),
        )
        assert cls == "fail"


class TestRunAutonomyDoctor:

    def test_returns_report(self):
        r = run_autonomy_doctor()
        assert isinstance(r, AutonomyDoctorReport)

    def test_covers_10_domains(self):
        r = run_autonomy_doctor()
        assert len(r.domains) == 10

    def test_live_all_ok_on_branch(self):
        r = run_autonomy_doctor()
        assert r.overall_cls == "ok", [
            (d.name, d.cls, d.reasons) for d in r.domains
        ]
        assert r.ok_count == 10
        assert r.warn_count == 0
        assert r.fail_count == 0

    def test_overall_next_action_set_when_clean(self):
        r = run_autonomy_doctor()
        assert "cleanly" in r.overall_next_action.lower()


class TestDoctorReportCounts:

    def test_empty_counts_zero(self):
        r = AutonomyDoctorReport()
        assert r.ok_count == 0
        assert r.warn_count == 0
        assert r.fail_count == 0

    def test_mixed_counts(self):
        r = AutonomyDoctorReport()
        r.domains = [
            DoctorDomainReport(name="a", cls="ok"),
            DoctorDomainReport(name="b", cls="warn"),
            DoctorDomainReport(name="c", cls="fail"),
            DoctorDomainReport(name="d", cls="ok"),
        ]
        assert r.ok_count == 2
        assert r.warn_count == 1
        assert r.fail_count == 1
