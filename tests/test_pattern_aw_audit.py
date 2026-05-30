"""Tests for engines._pattern_aw_audit (Wave 826)."""
from __future__ import annotations

from core.automation.payload_discoverer import (
    DiscoveryResult, _DISCOVERERS,
)
from engines._pattern_aw_audit import (
    PatternAWReport,
    PatternAWViolation,
    run_pattern_aw_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_aw_audit()
        assert not r.has_violations, [
            (v.domain, v.reason) for v in r.violations
        ]
        # All 3 registered discoverers should be clean
        assert "shipping_alert" in r.clean_discoverers
        assert "catalog_quality" in r.clean_discoverers
        assert "order_followup" in r.clean_discoverers

    def test_scans_three_discoverers(self):
        r = run_pattern_aw_audit()
        assert len(r.discoverers_scanned) == 3


class TestSyntheticDrift:

    def _swap(self, domain: str, fn):
        """Temporarily replace a discoverer + restore."""
        snapshot = dict(_DISCOVERERS)
        _DISCOVERERS[domain] = fn
        try:
            return run_pattern_aw_audit()
        finally:
            _DISCOVERERS.clear()
            _DISCOVERERS.update(snapshot)

    def test_wrong_return_type_flagged(self):
        r = self._swap(
            "shipping_alert",
            lambda: "not a DiscoveryResult",
        )
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any(
            "expected DiscoveryResult" in m for m in msgs
        ), msgs

    def test_domain_mismatch_flagged(self):
        r = self._swap(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="wrong_name",
                payload=[],
                source="x",
            ),
        )
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any(
            "expected 'shipping_alert'" in m for m in msgs
        ), msgs

    def test_non_list_payload_flagged(self):
        r = self._swap(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload="not a list",  # type: ignore
                source="x",
            ),
        )
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any("expected list" in m for m in msgs)

    def test_non_dict_row_flagged(self):
        r = self._swap(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[{"ok": 1}, "broken"],  # type: ignore
                source="x",
            ),
        )
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any("payload[1]" in m for m in msgs)

    def test_empty_source_flagged_when_ok(self):
        r = self._swap(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[],
                source="",
            ),
        )
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any("source is empty" in m for m in msgs)

    def test_discoverer_raise_flagged(self):
        def explode():
            raise RuntimeError("boom")
        r = self._swap("shipping_alert", explode)
        assert r.has_violations
        msgs = [
            v.reason for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert any("raised on invocation" in m for m in msgs)


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternAWReport().has_violations

    def test_with_violations(self):
        r = PatternAWReport()
        r.violations.append(PatternAWViolation(
            domain="x", reason="y",
        ))
        assert r.has_violations
