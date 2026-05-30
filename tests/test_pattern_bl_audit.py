"""Tests for engines._pattern_bl_audit (Wave 889)."""
from __future__ import annotations

from engines._pattern_bl_audit import (
    LegacyAlias,
    PatternBLReport,
    _LEGACY_CATALOG,
    run_pattern_bl_audit,
)


class TestCatalog:

    def test_5_aliases_tracked(self):
        assert len(_LEGACY_CATALOG) == 5

    def test_every_entry_is_4_tuple(self):
        for entry in _LEGACY_CATALOG:
            assert isinstance(entry, tuple)
            assert len(entry) == 4
            disc, knob, std, leg = entry
            assert disc
            assert knob
            assert std.startswith("SHOPAI_")
            assert "DISCOVER_" in std
            assert leg.startswith("SHOPAI_")


class TestRunAudit:

    def test_never_fails(self):
        r = run_pattern_bl_audit()
        assert not r.has_violations
        # informational invariant

    def test_returns_all_aliases(self):
        r = run_pattern_bl_audit()
        assert len(r.aliases) == 5


class TestEnvDetection:

    def test_legacy_only_counted(self, monkeypatch):
        for _, _, std, leg in _LEGACY_CATALOG:
            monkeypatch.delenv(std, raising=False)
            monkeypatch.delenv(leg, raising=False)
        # Set just one legacy
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_VIP_USD", "1000",
        )
        r = run_pattern_bl_audit()
        assert r.legacy_only_count == 1
        assert r.migrated_count == 0

    def test_migrated_only_counted(self, monkeypatch):
        for _, _, std, leg in _LEGACY_CATALOG:
            monkeypatch.delenv(std, raising=False)
            monkeypatch.delenv(leg, raising=False)
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_VIP_USD",
            "1000",
        )
        r = run_pattern_bl_audit()
        assert r.migrated_count == 1
        assert r.legacy_only_count == 0

    def test_both_set_redundant(self, monkeypatch):
        for _, _, std, leg in _LEGACY_CATALOG:
            monkeypatch.delenv(std, raising=False)
            monkeypatch.delenv(leg, raising=False)
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_VIP_USD",
            "1000",
        )
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_VIP_USD", "500",
        )
        r = run_pattern_bl_audit()
        assert r.both_set_count == 1
        # Standard counts toward migrated when also legacy_set
        # is False, but here both are set so neither pure
        # bucket includes it.
        assert r.migrated_count == 0
        assert r.legacy_only_count == 0


class TestReportDataclass:

    def test_empty(self):
        r = PatternBLReport()
        assert not r.has_violations
        assert r.legacy_only_count == 0
        assert r.both_set_count == 0
        assert r.migrated_count == 0

    def test_legacy_only_isolation(self):
        r = PatternBLReport()
        r.aliases.append(LegacyAlias(
            discoverer="x", knob="y",
            standard_env="A", legacy_env="B",
            standard_set=False, legacy_set=True,
        ))
        assert r.legacy_only_count == 1
        assert r.migrated_count == 0
