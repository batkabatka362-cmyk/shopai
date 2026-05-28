"""Tests for engines._pattern_al_audit (Wave 319-321)."""
from __future__ import annotations

from engines._pattern_al_audit import (
    PatternALReport,
    PatternALViolation,
    _DOMAIN_STATE_MODULES,
    _read_state_path,
    run_pattern_al_audit,
)


class TestCatalog:

    def test_all_9_domains(self):
        assert set(_DOMAIN_STATE_MODULES.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
            "catalog_quality",
        }

    def test_state_modules_end_with_state(self):
        for d, (_, modname) in _DOMAIN_STATE_MODULES.items():
            assert modname.endswith("_state"), (d, modname)


class TestReadStatePath:

    def test_reads_real_module(self):
        path, reason = _read_state_path(
            "returns_management", "refund_state",
        )
        assert path is not None
        assert "refund_state.json" in path
        assert reason == ""

    def test_missing_module(self):
        path, reason = _read_state_path(
            "nonexistent_pkg", "no_module",
        )
        assert path is None
        assert "import failed" in reason


class TestRunPatternALAudit:

    def test_returns_report(self):
        r = run_pattern_al_audit()
        assert isinstance(r, PatternALReport)

    def test_scans_all_9_domains(self):
        r = run_pattern_al_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_al_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8

    def test_paths_under_data(self):
        r = run_pattern_al_audit()
        for domain, path in r.paths_by_domain.items():
            assert path.startswith("data/"), (
                f"{domain} path is outside data/: {path}"
            )

    def test_paths_pairwise_distinct(self):
        r = run_pattern_al_audit()
        paths = list(r.paths_by_domain.values())
        assert len(paths) == len(set(paths))

    def test_each_path_ends_with_state_json(self):
        r = run_pattern_al_audit()
        for domain, path in r.paths_by_domain.items():
            assert path.endswith("_state.json"), (
                f"{domain} path doesn't match convention: "
                f"{path}"
            )


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternALViolation(domain="x")
        assert v.state_path == ""
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternALReport()
        assert not r.has_violations
        assert r.paths_by_domain == {}
