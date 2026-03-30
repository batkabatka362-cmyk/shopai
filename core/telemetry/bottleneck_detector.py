"""BottleneckDetector — identifies performance bottlenecks from traces."""
from __future__ import annotations
from typing import Any

from .tracer import Tracer


class BottleneckDetector:
    """Analyzes traces to find performance bottlenecks."""

    def __init__(self) -> None:
        self._tracer = Tracer()

    def analyze(self, trace_id: str) -> dict[str, Any]:
        """Analyze a single trace for bottlenecks."""
        spans = self._tracer.get_trace(trace_id)
        if not spans:
            return {"trace_id": trace_id, "bottlenecks": []}

        total_ms = sum(s["duration_ms"] for s in spans)
        bottlenecks = []

        for span in spans:
            pct = span["duration_ms"] / total_ms * 100 if total_ms > 0 else 0
            if pct > 30:
                bottlenecks.append({
                    "span": span["name"],
                    "duration_ms": span["duration_ms"],
                    "pct_of_total": round(pct, 1),
                    "severity": "critical" if pct > 60 else "high" if pct > 40 else "medium",
                })

        bottlenecks.sort(key=lambda b: b["duration_ms"], reverse=True)
        return {
            "trace_id": trace_id,
            "total_ms": round(total_ms, 2),
            "bottlenecks": bottlenecks,
            "slowest": bottlenecks[0] if bottlenecks else None,
        }

    def analyze_system(self) -> dict[str, Any]:
        """Analyze recent traces for system-wide bottlenecks."""
        traces = self._tracer.get_recent_traces(limit=50)
        span_times: dict[str, list[float]] = {}

        for trace in traces:
            for span_info in self._tracer.get_trace(trace.get("trace_id", "")):
                name = span_info["name"]
                span_times.setdefault(name, []).append(span_info["duration_ms"])

        hotspots = []
        for name, times in span_times.items():
            avg = sum(times) / len(times) if times else 0
            if avg > 100:  # >100ms average
                hotspots.append({
                    "span": name,
                    "avg_ms": round(avg, 2),
                    "max_ms": round(max(times), 2),
                    "call_count": len(times),
                })

        hotspots.sort(key=lambda h: h["avg_ms"], reverse=True)
        return {
            "traces_analyzed": len(traces),
            "hotspots": hotspots[:10],
            "total_unique_spans": len(span_times),
        }
