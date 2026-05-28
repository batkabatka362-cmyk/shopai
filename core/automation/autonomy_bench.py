"""Autonomy bench (W341): per-domain bridge latency measurement.

When the autonomous cycle runs hourly across 20+ stores, each
bridge's wall-clock cost matters. If one domain's
``maybe_auto_pause_X`` takes 3 seconds while others finish in
50ms, the per-cycle budget eats that domain's tax 24x/day.

``autonomy-bench`` runs each domain's bridge function in
isolation N times + reports median + max latency per domain.
Identifies the slowest substrate without firing real Shopify
writes (the bridge is read-only by design: it analyzes recent
health events and optionally flips the pause flag).

Use cases:
  - operator routine ops: "which domain is slowest"
  - pre-deploy regression check: "did the new substrate
    slow down domain X"
  - capacity planning: "can the cycle complete inside the
    cron-window budget"
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from importlib import import_module


# Per-domain (display name, package, health module name, bridge
# function name).
_DOMAIN_BRIDGES = [
    (
        "customer_support_refund",
        "returns_management",
        "refund_health",
        "maybe_auto_pause_refunds",
    ),
    (
        "marketing_budget",
        "roas_guardrails",
        "budget_health",
        "maybe_auto_pause_budget",
    ),
    (
        "fulfillment",
        "fulfillment_autonomy",
        "fulfillment_health",
        "maybe_auto_pause_fulfillment",
    ),
    (
        "inventory",
        "inventory_autonomy",
        "inventory_health",
        "maybe_auto_pause_inventory",
    ),
    (
        "discount_cleanup",
        "discount_cleanup_autonomy",
        "cleanup_health",
        "maybe_auto_pause_cleanup",
    ),
    (
        "order_followup",
        "order_followup_autonomy",
        "followup_health",
        "maybe_auto_pause_followup",
    ),
    (
        "product_seo",
        "product_seo_autonomy",
        "seo_health",
        "maybe_auto_pause_seo",
    ),
    (
        "customer_outreach",
        "customer_outreach_autonomy",
        "outreach_health",
        "maybe_auto_pause_outreach",
    ),
]


@dataclass
class BenchDomainResult:
    domain: str
    runs: int = 0
    median_ms: float = 0.0
    max_ms: float = 0.0
    min_ms: float = 0.0
    total_ms: float = 0.0
    error: str = ""


@dataclass
class BenchReport:
    domains: list[BenchDomainResult] = field(
        default_factory=list,
    )
    runs_per_domain: int = 3
    total_ms: float = 0.0
    slowest_domain: str = ""
    slowest_median_ms: float = 0.0

    @property
    def domain_count(self) -> int:
        return len(self.domains)


def _bench_one_bridge(
    domain: str,
    pkg: str,
    health_modname: str,
    fn_name: str,
    runs: int,
) -> BenchDomainResult:
    """Run one bridge `runs` times + collect latency stats."""
    result = BenchDomainResult(domain=domain, runs=runs)
    try:
        mod = import_module(f"engines.{pkg}.{health_modname}")
    except Exception as exc:  # noqa: BLE001
        result.error = f"import failed: {exc!s:.80}"
        return result
    fn = getattr(mod, fn_name, None)
    if fn is None:
        result.error = f"{fn_name!r} not found"
        return result
    timings_ms: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            fn(window_hours=24.0)
        except Exception as exc:  # noqa: BLE001
            result.error = f"raised: {exc!s:.80}"
            return result
        dt_ms = (time.perf_counter() - t0) * 1000.0
        timings_ms.append(dt_ms)
    if timings_ms:
        result.median_ms = statistics.median(timings_ms)
        result.max_ms = max(timings_ms)
        result.min_ms = min(timings_ms)
        result.total_ms = sum(timings_ms)
    return result


def run_autonomy_bench(
    *,
    runs_per_domain: int = 3,
) -> BenchReport:
    """Benchmark every autonomy domain's bridge."""
    report = BenchReport(runs_per_domain=runs_per_domain)
    for tup in _DOMAIN_BRIDGES:
        result = _bench_one_bridge(
            *tup, runs=runs_per_domain,
        )
        report.domains.append(result)
        report.total_ms += result.total_ms
        if result.median_ms > report.slowest_median_ms:
            report.slowest_median_ms = result.median_ms
            report.slowest_domain = result.domain
    return report
