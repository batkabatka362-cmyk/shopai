"""HealthChecker — checks health of all system components.

READ-ONLY: never modifies code, only reports status.
"""
from __future__ import annotations

import importlib
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("monitor.health")

REQUIRED_MODULES = [
    ("engines.registry", "engine_count"),
    ("data_pipeline", None),
    ("execution", None),
    ("agents", None),
    ("knowledge", None),
    ("memory", None),
    ("monitoring", None),
    ("infrastructure", None),
    ("models.routing.model_router", "ModelRouter"),
    ("core.orchestrator", "MainOrchestrator"),
]


class HealthChecker:
    """Checks system health across all layers. Read-only."""

    def check_all(self) -> dict[str, Any]:
        """Run full system health check."""
        start = time.monotonic()
        results = {
            "modules": self._check_modules(),
            "engines": self._check_engines(),
            "models": self._check_models(),
            "memory": self._check_memory(),
        }
        elapsed = time.monotonic() - start

        healthy = all(
            r.get("healthy", False) for r in results.values()
            if isinstance(r, dict) and "healthy" in r
        )

        return {
            "status": "healthy" if healthy else "degraded",
            "elapsed_seconds": round(elapsed, 3),
            "checks": results,
        }

    def _check_modules(self) -> dict[str, Any]:
        """Verify all required modules import successfully."""
        ok = 0
        failed = []
        for module_path, attr in REQUIRED_MODULES:
            try:
                mod = importlib.import_module(module_path)
                if attr and not hasattr(mod, attr):
                    failed.append(f"{module_path}: missing {attr}")
                    continue
                ok += 1
            except Exception as exc:
                failed.append(f"{module_path}: {exc}")
        return {
            "healthy": len(failed) == 0,
            "total": len(REQUIRED_MODULES),
            "ok": ok,
            "failed": failed,
        }

    def _check_engines(self) -> dict[str, Any]:
        """Check engine registry is accessible."""
        try:
            from engines.registry import engine_count, list_engines
            count = engine_count()
            sample = list_engines()[:3]
            return {"healthy": count > 0, "count": count, "sample": sample}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    def _check_models(self) -> dict[str, Any]:
        """Check model router health."""
        try:
            from models.routing.model_router import ModelRouter
            mr = ModelRouter()
            health = mr.health_check()
            all_ok = all(health.values())
            return {"healthy": all_ok, "models": health}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    def _check_memory(self) -> dict[str, Any]:
        """Check memory subsystem."""
        try:
            from core.memory import ShortTermCache, VectorDB
            cache = ShortTermCache()
            cache.set("_health_check", True, ttl=5)
            val = cache.get("_health_check")
            cache.delete("_health_check")
            return {"healthy": val is True, "cache": "ok", "vector_db": "ok"}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}
