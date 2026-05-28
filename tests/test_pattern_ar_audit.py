"""Tests for engines._pattern_ar_audit (Wave 363-368)."""
from __future__ import annotations

from engines._pattern_ar_audit import (
    PatternARReport,
    PatternARViolation,
    _CATALOGS,
    _EXPECTED_DOMAIN_COUNT,
    _read_catalog_size,
    run_pattern_ar_audit,
)


class TestCatalogList:

    def test_expected_count_is_8(self):
        assert _EXPECTED_DOMAIN_COUNT == 8

    def test_at_least_15_catalogs_registered(self):
        # Phase 25 audit family + core/automation modules
        # should yield at least 15 catalogs
        assert len(_CATALOGS) >= 15

    def test_every_entry_is_3_tuple(self):
        for entry in _CATALOGS:
            assert len(entry) == 3
            mod_name, attr, is_list = entry
            assert isinstance(mod_name, str)
            assert isinstance(attr, str)
            assert isinstance(is_list, bool)

    def test_no_duplicate_catalog_keys(self):
        keys = [
            f"{m}.{a}" for m, a, _ in _CATALOGS
        ]
        # Per-audit duplicates allowed (e.g. ac/aj share name)
        # but the combined module.attr key must be unique
        assert len(keys) == len(set(keys))


class TestReadCatalogSize:

    def test_real_dict_catalog(self):
        count, reason = _read_catalog_size(
            "engines._pattern_w_audit",
            "_DOMAIN_HEALTH_MODULES",
            False,
        )
        assert count == 8
        assert reason == ""

    def test_real_list_catalog(self):
        count, reason = _read_catalog_size(
            "core.automation.autonomy_smoke",
            "_DOMAINS",
            True,
        )
        assert count == 8
        assert reason == ""

    def test_missing_module(self):
        count, reason = _read_catalog_size(
            "no.such.module", "X", False,
        )
        assert count is None
        assert "import failed" in reason

    def test_missing_attr(self):
        count, reason = _read_catalog_size(
            "engines._pattern_w_audit",
            "NOT_AN_ATTR",
            False,
        )
        assert count is None
        assert "not found" in reason


class TestRunPatternARAudit:

    def test_returns_report(self):
        r = run_pattern_ar_audit()
        assert isinstance(r, PatternARReport)

    def test_scans_all_registered_catalogs(self):
        r = run_pattern_ar_audit()
        assert len(r.catalogs_scanned) == len(_CATALOGS)

    def test_live_passes(self):
        r = run_pattern_ar_audit()
        assert not r.has_violations, r.violations
        assert (
            len(r.clean_catalogs) == len(_CATALOGS)
        )

    def test_sizes_by_catalog_populated(self):
        r = run_pattern_ar_audit()
        for key, count in r.sizes_by_catalog.items():
            assert count == _EXPECTED_DOMAIN_COUNT, (
                f"{key} has {count}, expected "
                f"{_EXPECTED_DOMAIN_COUNT}"
            )


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternARViolation(catalog="x.y")
        assert v.expected_count == _EXPECTED_DOMAIN_COUNT
        assert v.actual_count == 0
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternARReport()
        assert not r.has_violations
        assert r.sizes_by_catalog == {}
