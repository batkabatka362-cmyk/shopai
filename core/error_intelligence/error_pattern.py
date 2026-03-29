"""ErrorPatternDetector — detects recurring error patterns across the system."""
from __future__ import annotations

import threading
import time
from typing import Any


class ErrorPatternDetector:
    """Detects patterns in errors: recurring, cascading, time-correlated."""

    def __init__(self) -> None:
        self._errors: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, engine_name: str, error: str, step: str = "", severity: str = "medium") -> None:
        """Record an error occurrence."""
        with self._lock:
            self._errors.append({
                "engine": engine_name,
                "error": error[:200],
                "step": step,
                "severity": severity,
                "timestamp": time.time(),
            })
            if len(self._errors) > 10000:
                self._errors = self._errors[-10000:]

    def detect_patterns(self) -> dict[str, Any]:
        """Detect all patterns in recorded errors."""
        with self._lock:
            errors = list(self._errors)

        return {
            "recurring": self._find_recurring(errors),
            "cascading": self._find_cascading(errors),
            "time_clusters": self._find_time_clusters(errors),
            "engine_hotspots": self._find_hotspots(errors),
            "total_errors": len(errors),
        }

    def _find_recurring(self, errors: list[dict]) -> list[dict]:
        """Find errors that keep happening."""
        counts: dict[str, dict] = {}
        for e in errors:
            key = f"{e['engine']}:{e['error'][:50]}"
            if key not in counts:
                counts[key] = {"engine": e["engine"], "error": e["error"][:80], "count": 0, "first": e["timestamp"], "last": e["timestamp"]}
            counts[key]["count"] += 1
            counts[key]["last"] = e["timestamp"]

        recurring = [v for v in counts.values() if v["count"] >= 3]
        recurring.sort(key=lambda x: x["count"], reverse=True)
        return recurring[:10]

    def _find_cascading(self, errors: list[dict]) -> list[dict]:
        """Find errors that trigger other errors (within 5 seconds)."""
        cascades = []
        for i, e1 in enumerate(errors):
            related = []
            for e2 in errors[i+1:i+10]:
                if 0 < e2["timestamp"] - e1["timestamp"] < 5 and e2["engine"] != e1["engine"]:
                    related.append(e2["engine"])
            if related:
                cascades.append({
                    "origin_engine": e1["engine"],
                    "origin_error": e1["error"][:60],
                    "affected_engines": list(set(related)),
                    "cascade_size": len(related),
                })

        # Deduplicate
        seen = set()
        unique = []
        for c in cascades:
            key = f"{c['origin_engine']}:{c['origin_error'][:30]}"
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique[:5]

    def _find_time_clusters(self, errors: list[dict]) -> list[dict]:
        """Find time periods with high error rates."""
        if not errors:
            return []

        # Group by 5-minute windows
        windows: dict[int, int] = {}
        for e in errors:
            window = int(e["timestamp"] // 300)
            windows[window] = windows.get(window, 0) + 1

        avg = sum(windows.values()) / len(windows) if windows else 0
        spikes = []
        for window, count in windows.items():
            if count > avg * 2 and count >= 5:
                spikes.append({
                    "window_start": window * 300,
                    "error_count": count,
                    "above_avg_by": round(count / avg, 1) if avg > 0 else 0,
                })
        return sorted(spikes, key=lambda x: x["error_count"], reverse=True)[:5]

    def _find_hotspots(self, errors: list[dict]) -> list[dict]:
        """Find engines with the most errors."""
        counts: dict[str, int] = {}
        for e in errors:
            counts[e["engine"]] = counts.get(e["engine"], 0) + 1

        hotspots = [{"engine": eng, "error_count": cnt} for eng, cnt in counts.items()]
        hotspots.sort(key=lambda x: x["error_count"], reverse=True)
        return hotspots[:10]
