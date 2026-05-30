"""Tests for engines._pattern_bn_audit (Wave 893)."""
from __future__ import annotations

from engines._pattern_bn_audit import (
    PatternBNReport,
    PatternBNViolation,
    _EXPECTED_FIELDS,
    _EXPECTED_TOKENS,
    run_pattern_bn_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bn_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self):
        r = run_pattern_bn_audit()
        assert len(r.invariants_checked) == 4


class TestExpectedSchema:

    def test_expected_fields_complete(self):
        # The catalog must include verdict in the JSON
        # envelope check (added at runtime not in
        # _EXPECTED_FIELDS, but verdict is a property).
        assert "armed_total" in _EXPECTED_FIELDS
        assert "fires_invoked" in _EXPECTED_FIELDS
        assert "alerts_critical" in _EXPECTED_FIELDS

    def test_expected_tokens_complete(self):
        # Text output must include these key= prefixes
        assert "verdict=" in _EXPECTED_TOKENS
        assert "armed=" in _EXPECTED_TOKENS
        assert "fires=" in _EXPECTED_TOKENS


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBNReport().has_violations

    def test_with_violations(self):
        r = PatternBNReport()
        r.violations.append(PatternBNViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
