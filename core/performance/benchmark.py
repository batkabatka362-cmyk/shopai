"""Benchmark — full system performance measurement."""
from __future__ import annotations

import random
import time
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("performance.benchmark")


class Benchmark:
    """Full system benchmark suite."""

    def run_full(self) -> dict[str, Any]:
        """Run complete benchmark suite."""
        results = {}
        start = time.monotonic()

        results["startup"] = self._bench_startup()
        results["engine_speed"] = self._bench_engine_speed()
        results["mass_engines"] = self._bench_mass_engines(200)
        results["concurrent"] = self._bench_concurrent(10)
        results["intelligence"] = self._bench_intelligence()
        results["unified"] = self._bench_unified()

        total = time.monotonic() - start
        results["total_seconds"] = round(total, 2)

        return results

    def _bench_startup(self) -> dict[str, Any]:
        t = time.monotonic()
        from core.orchestrator import MainOrchestrator
        orch = MainOrchestrator()
        orch.initialize()
        elapsed = time.monotonic() - t
        orch.shutdown()
        return {"startup_ms": round(elapsed * 1000, 1)}

    def _bench_engine_speed(self, iterations: int = 30) -> dict[str, Any]:
        from core.orchestrator import MainOrchestrator
        from engines.base.engine_types import EngineInput
        from engines.registry import get_engine

        orch = MainOrchestrator()
        orch.initialize()
        e = get_engine("pricing")
        data = {"products": [{"name": "X", "price": 30, "cost": 10}]}

        # Warmup
        for i in range(3):
            e.run(EngineInput(task_id=f"w{i}", engine_name="pricing", data=data))

        times = []
        for i in range(iterations):
            t = time.monotonic()
            e.run(EngineInput(task_id=f"b{i}", engine_name="pricing", data=data))
            times.append((time.monotonic() - t) * 1000)

        orch.shutdown()
        times.sort()
        return {
            "iterations": iterations,
            "avg_ms": round(sum(times) / len(times), 2),
            "min_ms": round(times[0], 2),
            "p50_ms": round(times[len(times)//2], 2),
            "p95_ms": round(times[int(len(times)*0.95)], 2),
            "p99_ms": round(times[-1], 2),
            "ops_per_sec": round(len(times) / (sum(times) / 1000), 0),
        }

    def _bench_mass_engines(self, count: int) -> dict[str, Any]:
        from core.orchestrator import MainOrchestrator
        from engines.base.engine_types import EngineInput, EngineStatus
        from engines.registry import get_engine, list_engines

        orch = MainOrchestrator()
        orch.initialize()
        sample = random.sample(list_engines(), min(count, len(list_engines())))

        t = time.monotonic()
        passed = 0
        for name in sample:
            e = get_engine(name)
            data = {f: [{"name": "T", "price": 30, "cost": 10}] if "product" in f.lower() else {}
                    for f in e.required_input_fields}
            out = e.run(EngineInput(task_id=f"mass_{name}", engine_name=name, data=data))
            if out.status == EngineStatus.COMPLETED:
                passed += 1

        elapsed = time.monotonic() - t
        orch.shutdown()
        return {
            "engines_tested": count,
            "passed": passed,
            "pass_rate": round(passed / count * 100, 1),
            "total_seconds": round(elapsed, 2),
            "avg_ms_per_engine": round(elapsed / count * 1000, 2),
        }

    def _bench_concurrent(self, threads: int) -> dict[str, Any]:
        from engines.base.engine_types import EngineInput
        from engines.registry import get_engine, list_engines
        from core.orchestrator import MainOrchestrator

        orch = MainOrchestrator()
        orch.initialize()
        sample = random.sample(list_engines(), threads)
        results = []
        errors = []

        def worker(name):
            try:
                e = get_engine(name)
                data = {f: {} for f in e.required_input_fields}
                out = e.run(EngineInput(task_id=f"conc_{name}", engine_name=name, data=data))
                results.append(out.status.value)
            except Exception as exc:
                errors.append(str(exc))

        t = time.monotonic()
        ts = [threading.Thread(target=worker, args=(n,)) for n in sample]
        for thread in ts:
            thread.start()
        for thread in ts:
            thread.join(timeout=30)
        elapsed = time.monotonic() - t

        orch.shutdown()
        return {
            "threads": threads,
            "completed": len(results),
            "errors": len(errors),
            "total_seconds": round(elapsed, 2),
        }

    def _bench_intelligence(self) -> dict[str, Any]:
        times = {}

        t = time.monotonic()
        from core.intelligence.pricing_intelligence import PricingIntelligence
        PricingIntelligence().compute_demand_curve([
            {"price": 20, "units_sold": 200}, {"price": 25, "units_sold": 150}, {"price": 30, "units_sold": 100},
        ])
        times["pricing"] = round((time.monotonic() - t) * 1000, 2)

        t = time.monotonic()
        from core.intelligence.seo_intelligence import SEOIntelligence
        SEOIntelligence().audit_page({"title": "Test", "content": "word " * 200, "keyword": "test"})
        times["seo"] = round((time.monotonic() - t) * 1000, 2)

        t = time.monotonic()
        from core.intelligence.email_intelligence import EmailIntelligence
        EmailIntelligence().score_subject_line("50% off wireless earbuds today only!")
        times["email"] = round((time.monotonic() - t) * 1000, 2)

        t = time.monotonic()
        from core.intelligence.forecasting import Forecasting
        Forecasting().forecast([100, 120, 115, 130, 125, 140], periods=7)
        times["forecast"] = round((time.monotonic() - t) * 1000, 2)

        return {"module_times_ms": times, "total_ms": round(sum(times.values()), 2)}

    def _bench_unified(self) -> dict[str, Any]:
        from core.intelligence.unified import UnifiedIntelligence
        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()

        t = time.monotonic()
        UnifiedIntelligence().full_store_analysis(
            products=sb.fetch_products(), customers=sb.fetch_customers(), orders=sb.fetch_orders(),
        )
        return {"unified_15_modules_ms": round((time.monotonic() - t) * 1000, 2)}
