"""LazyEngine — lazy-loads engines only when needed, with warmup support."""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.logger import get_logger
from engines.registry import get_engine, list_engines, engine_count

logger = get_logger("performance.lazy")


class LazyEngine:
    """Engine loader with lazy loading, warmup, and preloading."""

    def __init__(self) -> None:
        self._warmup_done = False
        self._preloaded: set[str] = set()
        self._load_times: dict[str, float] = {}

    def warmup(self, engine_names: list[str] | None = None) -> dict[str, Any]:
        """Pre-load frequently used engines into cache."""
        if engine_names is None:
            engine_names = [
                "product_selection", "pricing", "marketing", "inventory",
                "seo", "customer_segmentation", "content_generation",
                "email_marketing", "analytics", "forecasting",
            ]

        loaded = []
        failed = []
        start = time.monotonic()

        for name in engine_names:
            t0 = time.monotonic()
            try:
                get_engine(name)
                load_time = time.monotonic() - t0
                self._load_times[name] = load_time
                self._preloaded.add(name)
                loaded.append(name)
            except Exception as exc:
                failed.append({"engine": name, "error": str(exc)})

        elapsed = time.monotonic() - start
        self._warmup_done = True

        logger.info("Warmup complete: %d loaded, %d failed in %.3fs", len(loaded), len(failed), elapsed)
        return {
            "loaded": len(loaded),
            "failed": len(failed),
            "elapsed_seconds": round(elapsed, 3),
            "load_times": self._load_times,
            "failures": failed,
        }

    def warmup_async(self, engine_names: list[str] | None = None) -> None:
        """Warmup in background thread."""
        t = threading.Thread(target=self.warmup, args=(engine_names,), daemon=True)
        t.start()

    def is_loaded(self, engine_name: str) -> bool:
        return engine_name in self._preloaded

    def get_load_stats(self) -> dict[str, Any]:
        return {
            "warmup_done": self._warmup_done,
            "preloaded_count": len(self._preloaded),
            "total_engines": engine_count(),
            "avg_load_time": round(sum(self._load_times.values()) / max(len(self._load_times), 1), 4),
            "slowest": max(self._load_times.items(), key=lambda x: x[1]) if self._load_times else None,
        }
