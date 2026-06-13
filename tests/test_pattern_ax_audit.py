"""Tests for engines._pattern_ax_audit (Wave 833)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engines._pattern_ax_audit import (
    PatternAXReport,
    PatternAXViolation,
    _DOMAIN_PAIRS,
    _applier_expected_actions,
    _discoverer_emitted_actions,
    run_pattern_ax_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_ax_audit()
        assert not r.has_violations, [
            (v.domain, v.reason) for v in r.violations
        ]
        assert len(r.clean_pairs) == 8

    def test_scans_all_8_pairs(self):
        r = run_pattern_ax_audit()
        assert len(r.domains_scanned) == 8


class TestApplierScan:

    def test_inventory_applier_accepts_two_actions(self):
        # inventory_applier uses `action not in ("reorder",
        # "restock")` -- both must be expected
        path = Path(
            "engines/inventory_autonomy/inventory_applier.py"
        )
        actions = _applier_expected_actions(path)
        assert "reorder" in actions
        assert "restock" in actions

    def test_shipping_alert_applier_one_action(self):
        path = Path(
            "engines/shipping_alert_autonomy/"
            "shipping_applier.py"
        )
        actions = _applier_expected_actions(path)
        assert "tag_shipping" in actions

    def test_missing_file_returns_empty(self, tmp_path):
        actions = _applier_expected_actions(
            tmp_path / "nope.py",
        )
        assert actions == set()


class TestDiscovererScan:

    def test_shipping_alert_emits_tag_shipping(self):
        actions = _discoverer_emitted_actions(
            "core.automation.discoverers.shipping_alert",
        )
        assert "tag_shipping" in actions

    def test_discount_cleanup_emits_deactivate(self):
        actions = _discoverer_emitted_actions(
            "core.automation.discoverers.discount_cleanup",
        )
        assert "deactivate" in actions

    def test_nonexistent_module_returns_empty(self):
        actions = _discoverer_emitted_actions(
            "does_not_exist",
        )
        assert actions == set()


class TestSyntheticDrift:

    def test_drift_simulation(self, tmp_path):
        # Plant a fake (discoverer, applier) pair where the
        # discoverer emits action="WRONG" but applier accepts
        # action="right" -> Pattern AX should flag.
        # Use the runtime override approach: monkey-patch
        # _DOMAIN_PAIRS for this test.
        applier = tmp_path / "engines" / "synthetic_autonomy"
        applier.mkdir(parents=True)
        ap = applier / "synth_applier.py"
        ap.write_text(
            'def f(action):\n'
            '    if action != "right":\n'
            '        return "skip"\n',
            encoding="utf-8",
        )
        original = dict(_DOMAIN_PAIRS)
        try:
            _DOMAIN_PAIRS.clear()
            _DOMAIN_PAIRS["synthetic"] = (
                "core.automation.discoverers.shipping_alert",
                ap.relative_to(tmp_path).as_posix(),
            )
            r = run_pattern_ax_audit(repo_root=tmp_path)
        finally:
            _DOMAIN_PAIRS.clear()
            _DOMAIN_PAIRS.update(original)
        # shipping_alert discoverer emits "tag_shipping"
        # whereas our synthetic applier expects "right".
        assert r.has_violations
        bad = next(
            v for v in r.violations
            if v.domain == "synthetic"
        )
        assert "tag_shipping" in bad.discoverer_action


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternAXReport().has_violations

    def test_with_violations(self):
        r = PatternAXReport()
        r.violations.append(PatternAXViolation(
            domain="x", discoverer_action="a",
            applier_action="b", reason="drift",
        ))
        assert r.has_violations
