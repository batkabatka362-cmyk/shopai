"""StartupOptimizer — minimize startup time and memory usage.

Techniques:
  - Deferred imports (only load what's needed)
  - Engine registry lazy loading (no upfront iteration)
  - Model singleton (share across all engines)
  - Intelligence module lazy init
  - Memory-efficient data structures
"""
from __future__ import annotations

import time
import sys
from typing import Any

from utils.logger import get_logger

logger = get_logger("performance.startup")


class StartupOptimizer:
    """Optimizes system startup and memory usage."""

    def profile_startup(self) -> dict[str, Any]:
        """Profile startup time for each component."""
        timings = {}

        t = time.monotonic()
        from engines.registry import engine_count
        timings["registry_import"] = round((time.monotonic() - t) * 1000, 1)

        t = time.monotonic()
        from core.orchestrator import MainOrchestrator
        timings["orchestrator_import"] = round((time.monotonic() - t) * 1000, 1)

        t = time.monotonic()
        orch = MainOrchestrator()
        timings["orchestrator_create"] = round((time.monotonic() - t) * 1000, 1)

        t = time.monotonic()
        orch.initialize()
        timings["orchestrator_init"] = round((time.monotonic() - t) * 1000, 1)

        total = sum(timings.values())
        timings["total"] = round(total, 1)
        timings["engine_count"] = engine_count()

        orch.shutdown()

        return {
            "timings_ms": timings,
            "bottleneck": max(timings.items(), key=lambda x: x[1] if x[0] != "total" else 0)[0],
            "acceptable": total < 500,
        }

    def profile_memory(self) -> dict[str, Any]:
        """Profile memory usage of key components."""
        sizes = {}

        from engines.registry import _ENGINE_MAP
        sizes["registry_map_entries"] = len(_ENGINE_MAP)
        sizes["registry_map_bytes"] = sys.getsizeof(_ENGINE_MAP)

        # Count loaded modules
        shopai_modules = [m for m in sys.modules if m.startswith("shopai") or m.startswith("engines") or m.startswith("core")]
        sizes["loaded_modules"] = len(shopai_modules)

        # Process memory (if available)
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            sizes["max_rss_mb"] = round(usage.ru_maxrss / 1024, 1)
        except (ImportError, AttributeError):
            sizes["max_rss_mb"] = "unavailable"

        return sizes

    def profile_engine_execution(self, engine_name: str = "pricing", iterations: int = 20) -> dict[str, Any]:
        """Profile engine execution speed."""
        from core.orchestrator import MainOrchestrator
        from engines.base.engine_types import EngineInput
        from engines.registry import get_engine

        orch = MainOrchestrator()
        orch.initialize()

        e = get_engine(engine_name)
        data = {f: [{"name": "T", "price": 30, "cost": 10}] if "product" in f.lower() else {}
                for f in e.required_input_fields}

        # Warmup
        for i in range(3):
            e.run(EngineInput(task_id=f"warmup_{i}", engine_name=engine_name, data=data))

        # Measure
        times = []
        for i in range(iterations):
            t = time.monotonic()
            e.run(EngineInput(task_id=f"perf_{i}", engine_name=engine_name, data=data))
            times.append((time.monotonic() - t) * 1000)

        orch.shutdown()

        times.sort()
        return {
            "engine": engine_name,
            "iterations": iterations,
            "avg_ms": round(sum(times) / len(times), 2),
            "min_ms": round(times[0], 2),
            "max_ms": round(times[-1], 2),
            "p50_ms": round(times[len(times) // 2], 2),
            "p95_ms": round(times[int(len(times) * 0.95)], 2),
            "p99_ms": round(times[-1], 2),
            "throughput_ops_sec": round(len(times) / (sum(times) / 1000), 0),
        }
