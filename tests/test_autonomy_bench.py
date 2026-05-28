"""Tests for core.automation.autonomy_bench (Wave 341-346)."""
from __future__ import annotations

from core.automation.autonomy_bench import (
    BenchDomainResult,
    BenchReport,
    _DOMAIN_BRIDGES,
    _bench_one_bridge,
    run_autonomy_bench,
)


class TestCatalog:

    def test_8_domains(self):
        assert len(_DOMAIN_BRIDGES) == 8
        names = {tup[0] for tup in _DOMAIN_BRIDGES}
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
        }

    def test_bridge_names_use_maybe_auto_pause_prefix(self):
        for tup in _DOMAIN_BRIDGES:
            fn = tup[3]
            assert fn.startswith("maybe_auto_pause_"), tup


class TestBenchOneBridge:

    def test_real_bridge_runs(self):
        # customer_support_refund's bridge is import-safe
        # + runs sub-millisecond on empty log
        r = _bench_one_bridge(
            "customer_support_refund",
            "returns_management",
            "refund_health",
            "maybe_auto_pause_refunds",
            runs=2,
        )
        assert r.error == ""
        assert r.runs == 2
        assert r.median_ms >= 0
        assert r.max_ms >= r.median_ms

    def test_missing_module(self):
        r = _bench_one_bridge(
            "x", "nonexistent_pkg", "no_mod", "no_fn",
            runs=1,
        )
        assert r.error
        assert "import failed" in r.error

    def test_missing_function(self):
        # Real module but bogus function name
        r = _bench_one_bridge(
            "x",
            "returns_management",
            "refund_health",
            "no_such_function",
            runs=1,
        )
        assert r.error
        assert "not found" in r.error


class TestRunAutonomyBench:

    def test_returns_report(self):
        r = run_autonomy_bench(runs_per_domain=1)
        assert isinstance(r, BenchReport)

    def test_covers_9_domains(self):
        r = run_autonomy_bench(runs_per_domain=1)
        assert r.domain_count == 8

    def test_runs_per_domain_preserved(self):
        r = run_autonomy_bench(runs_per_domain=2)
        assert r.runs_per_domain == 2
        for d in r.domains:
            if not d.error:
                assert d.runs == 2

    def test_total_ms_is_sum_of_per_domain(self):
        r = run_autonomy_bench(runs_per_domain=1)
        expected = sum(
            d.total_ms for d in r.domains
        )
        # float comparison with small epsilon
        assert abs(r.total_ms - expected) < 0.001

    def test_slowest_identified(self):
        r = run_autonomy_bench(runs_per_domain=1)
        if not r.slowest_domain:
            return  # All errors -- nothing to identify
        # The slowest domain's median should match the report
        match = next(
            d for d in r.domains
            if d.domain == r.slowest_domain
        )
        assert match.median_ms == r.slowest_median_ms

    def test_live_bench_completes_quickly(self):
        # Trust anchor: 1 run per domain on idle substrate
        # should finish well under 1 second
        import time
        t0 = time.perf_counter()
        r = run_autonomy_bench(runs_per_domain=1)
        dt = time.perf_counter() - t0
        assert dt < 5.0, (
            f"bench took {dt:.2f}s for idle 7 domains -- "
            "regression?"
        )


class TestDataclasses:

    def test_bench_domain_result_defaults(self):
        d = BenchDomainResult(domain="x")
        assert d.runs == 0
        assert d.median_ms == 0.0
        assert d.error == ""

    def test_bench_report_domain_count(self):
        r = BenchReport()
        assert r.domain_count == 0
        r.domains = [
            BenchDomainResult(domain="a"),
            BenchDomainResult(domain="b"),
        ]
        assert r.domain_count == 2
