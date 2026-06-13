"""Autonomy domain integration test (Wave 239-244).

Trust-anchor smoke that walks every autonomy domain's 5-piece
template + verifies the integration boundaries hold under real
import paths (not mocked).

Catches refactor breakage that unit tests miss:
  - circular import introduced when moving a helper
  - canonical entry point renamed
  - state module import-time crash
  - status function regresses to non-DomainSummary shape

For each of the 8 domains the test verifies:
  - all 5 template module files import cleanly
  - state module exports is_paused() + returns bool
  - autonomy_status's per-domain summary function returns a
    DomainSummary with all 7 canonical fields populated
  - the doctor wiring report classifies the domain
"""
from __future__ import annotations

from importlib import import_module

import pytest

from core.automation.autonomy_doctor import run_autonomy_doctor
from core.automation.autonomy_status import (
    DomainSummary,
    get_autonomy_status,
)
from engines._pattern_yprime_audit import _DOMAIN_TEMPLATE


# (autonomy-status name, package_dir, file_prefix) per domain.
# autonomy-status emits "customer_support" + "marketing" while
# the substrate catalog uses _refund / _budget suffixes; the
# tuple here records both so we can address the canonical
# entry-point in each context.
_DOMAINS = [
    (
        "customer_support",
        "returns_management",
        "refund",
    ),
    (
        "marketing",
        "roas_guardrails",
        "budget",
    ),
    (
        "fulfillment",
        "fulfillment_autonomy",
        "fulfillment",
    ),
    (
        "inventory",
        "inventory_autonomy",
        "inventory",
    ),
    (
        "discount_cleanup",
        "discount_cleanup_autonomy",
        "cleanup",
    ),
    (
        "order_followup",
        "order_followup_autonomy",
        "followup",
    ),
    (
        "product_seo",
        "product_seo_autonomy",
        "seo",
    ),
    (
        "customer_outreach",
        "customer_outreach_autonomy",
        "outreach",
    ),
]


_CANONICAL_SUMMARY_FIELDS = {
    "name", "verdict", "paused", "applied_count",
    "health_failure_ratio", "next_action", "reasons",
}


class TestTemplateImportability:

    @pytest.mark.parametrize(
        "pkg,prefix", [
            (pkg, pre) for _, pkg, pre in _DOMAINS
        ],
    )
    def test_log_imports(self, pkg, prefix):
        # Phase 11.B marketing uses ad_spend_log not budget_log
        # -- look up the canonical filename via the Y' catalog.
        domain_key = None
        for d, (p, _) in _DOMAIN_TEMPLATE.items():
            if p == f"engines/{pkg}":
                domain_key = d
                break
        assert domain_key is not None, pkg
        log_fname = _DOMAIN_TEMPLATE[domain_key][1]["log"]
        modname = log_fname.replace(".py", "")
        mod = import_module(f"engines.{pkg}.{modname}")
        assert mod is not None

    @pytest.mark.parametrize(
        "pkg,prefix", [
            (pkg, pre) for _, pkg, pre in _DOMAINS
        ],
    )
    def test_state_imports_and_is_paused_returns_bool(
        self, pkg, prefix,
    ):
        mod = import_module(f"engines.{pkg}.{prefix}_state")
        assert hasattr(mod, "is_paused")
        result = mod.is_paused()
        assert isinstance(result, bool), (
            f"{pkg}/{prefix}_state.is_paused() returned "
            f"{type(result).__name__}, expected bool"
        )

    @pytest.mark.parametrize(
        "pkg,prefix", [
            (pkg, pre) for _, pkg, pre in _DOMAINS
        ],
    )
    def test_health_imports(self, pkg, prefix):
        mod = import_module(f"engines.{pkg}.{prefix}_health")
        assert mod is not None

    @pytest.mark.parametrize(
        "pkg,prefix", [
            (pkg, pre) for _, pkg, pre in _DOMAINS
        ],
    )
    def test_applier_imports(self, pkg, prefix):
        mod = import_module(f"engines.{pkg}.{prefix}_applier")
        assert mod is not None

    @pytest.mark.parametrize(
        "pkg,prefix", [
            (pkg, pre) for _, pkg, pre in _DOMAINS
        ],
    )
    def test_status_imports(self, pkg, prefix):
        # Phase 11.A/B name their status modules differently;
        # use the Y' catalog as the source of truth.
        domain_key = None
        for d, (p, _) in _DOMAIN_TEMPLATE.items():
            if p == f"engines/{pkg}":
                domain_key = d
                break
        assert domain_key is not None, pkg
        status_fname = _DOMAIN_TEMPLATE[domain_key][1]["status"]
        modname = status_fname.replace(".py", "")
        mod = import_module(f"engines.{pkg}.{modname}")
        assert mod is not None


class TestSummaryBoundary:

    def test_status_returns_10_domain_summaries(self):
        report = get_autonomy_status()
        assert len(report.domains) == 10

    @pytest.mark.parametrize(
        "summary_name", [d[0] for d in _DOMAINS],
    )
    def test_each_summary_has_canonical_shape(
        self, summary_name,
    ):
        report = get_autonomy_status()
        match = next(
            (d for d in report.domains
             if d.name == summary_name),
            None,
        )
        assert match is not None, (
            f"domain {summary_name} not in autonomy_status "
            f"rollup -- got "
            f"{[d.name for d in report.domains]}"
        )
        for fld in _CANONICAL_SUMMARY_FIELDS:
            assert hasattr(match, fld), (
                f"{summary_name}.{fld} missing"
            )
        assert isinstance(match, DomainSummary)
        assert isinstance(match.verdict, str)
        assert isinstance(match.paused, bool)
        assert isinstance(match.applied_count, int)
        assert isinstance(match.next_action, str)
        assert isinstance(match.reasons, list)


class TestDoctorClassification:

    def test_doctor_covers_every_domain(self):
        r = run_autonomy_doctor()
        names = {d.name for d in r.domains}
        for canonical in [d[0] for d in _DOMAINS]:
            assert canonical in names, (
                f"doctor missed {canonical}"
            )

    def test_doctor_reports_overall_class(self):
        r = run_autonomy_doctor()
        assert r.overall_cls in {"ok", "warn", "fail"}

    def test_doctor_count_invariant(self):
        r = run_autonomy_doctor()
        assert (
            r.ok_count + r.warn_count + r.fail_count
            == len(r.domains)
        )


class TestStoreScope:

    def test_status_with_store_scopes(self):
        # store filter shouldn't crash regardless of data
        report = get_autonomy_status(store_id="store-xyz")
        assert report.store_id == "store-xyz"
        assert len(report.domains) == 10

    def test_doctor_with_store_scopes(self):
        r = run_autonomy_doctor(store_id="store-xyz")
        assert r.store_id == "store-xyz"
        assert len(r.domains) == 10
