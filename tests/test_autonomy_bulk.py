"""Tests for core.automation.autonomy_bulk (Wave 347-352)."""
from __future__ import annotations

import pytest

from core.automation.autonomy_bulk import (
    BulkDomainResult,
    BulkReport,
    _BULK_CONFIRM_ENV,
    _DOMAIN_STATE_MODULES,
    _confirm_enabled,
    run_bulk_pause,
    run_bulk_resume,
)


class TestCatalog:

    def test_10_domains(self):
        assert len(_DOMAIN_STATE_MODULES) == 10
        names = {tup[0] for tup in _DOMAIN_STATE_MODULES}
        assert names == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
            "catalog_quality",
            "shipping_alert",
        }

    def test_state_module_names_end_with_state(self):
        for tup in _DOMAIN_STATE_MODULES:
            assert tup[2].endswith("_state"), tup


class TestConfirmEnabled:

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv(
            _BULK_CONFIRM_ENV, raising=False,
        )
        assert not _confirm_enabled()

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setenv(_BULK_CONFIRM_ENV, "")
        assert not _confirm_enabled()

    @pytest.mark.parametrize(
        "value", ["0", "false", "no", "off"],
    )
    def test_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv(_BULK_CONFIRM_ENV, value)
        assert not _confirm_enabled()

    @pytest.mark.parametrize(
        "value", ["1", "true", "yes", "on", "TRUE", "Yes"],
    )
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv(_BULK_CONFIRM_ENV, value)
        assert _confirm_enabled()


class TestBulkPauseUnconfirmed:

    def test_without_env_returns_skipped(self, monkeypatch):
        monkeypatch.delenv(
            _BULK_CONFIRM_ENV, raising=False,
        )
        r = run_bulk_pause(reason="smoke")
        assert r.action == "pause"
        assert not r.confirm_set
        assert r.ok_count == 0
        assert r.error_count == 10
        for d in r.domains:
            assert d.action == "skipped"
            assert _BULK_CONFIRM_ENV in d.error

    def test_reason_preserved(self, monkeypatch):
        monkeypatch.delenv(
            _BULK_CONFIRM_ENV, raising=False,
        )
        r = run_bulk_pause(reason="custom reason")
        assert r.reason == "custom reason"


class TestBulkResumeUnconfirmed:

    def test_without_env_returns_skipped(self, monkeypatch):
        monkeypatch.delenv(
            _BULK_CONFIRM_ENV, raising=False,
        )
        r = run_bulk_resume()
        assert r.action == "resume"
        assert r.error_count == 10
        for d in r.domains:
            assert d.action == "skipped"


class TestBulkConfirmed:
    """When confirm is set, the calls actually execute. The
    Pattern J test-environment guard inside each state module
    means the state files don't actually persist during pytest,
    so these tests can run real pause/resume safely."""

    def test_pause_confirmed_executes(self, monkeypatch):
        monkeypatch.setenv(_BULK_CONFIRM_ENV, "1")
        r = run_bulk_pause(reason="ci test")
        assert r.confirm_set
        # All 7 should succeed (or surface a real error)
        for d in r.domains:
            assert d.action == "pause"

    def test_resume_confirmed_executes(self, monkeypatch):
        monkeypatch.setenv(_BULK_CONFIRM_ENV, "1")
        r = run_bulk_resume()
        assert r.confirm_set
        for d in r.domains:
            assert d.action == "resume"


class TestReportCounts:

    def test_ok_count(self):
        r = BulkReport()
        r.domains = [
            BulkDomainResult(domain="a", ok=True),
            BulkDomainResult(domain="b", ok=False),
            BulkDomainResult(domain="c", ok=True),
        ]
        assert r.ok_count == 2
        assert r.error_count == 1
        assert r.total == 3
