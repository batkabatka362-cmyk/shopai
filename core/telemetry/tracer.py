"""Tracer — distributed tracing with spans for engine execution.

Every engine run creates a trace. Each step creates a span within the trace.
Traces show exactly where time is spent and where failures occur.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("telemetry.tracer")


@dataclass
class Span:
    """A single span in a trace — one unit of work."""
    span_id: str
    trace_id: str
    name: str
    parent_id: str | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    status: str = "running"
    tags: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def finish(self, status: str = "ok", error: str | None = None) -> None:
        self.end_time = time.monotonic()
        self.status = status
        self.error = error

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return round((time.monotonic() - self.start_time) * 1000, 2)
        return round((self.end_time - self.start_time) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "tags": self.tags,
            "error": self.error,
        }


class Tracer:
    """Distributed tracer — creates traces and spans for engine execution."""

    _instance: Tracer | None = None
    _lock = threading.Lock()

    def __new__(cls) -> Tracer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._traces: dict[str, list[Span]] = {}
        self._active_spans: dict[str, Span] = {}
        self._storage_lock = threading.Lock()

    def start_trace(self, name: str, tags: dict[str, str] | None = None) -> Span:
        """Start a new trace (root span)."""
        trace_id = generate_id("trace")
        span = Span(
            span_id=generate_id("span"),
            trace_id=trace_id,
            name=name,
            tags=tags or {},
        )
        with self._storage_lock:
            self._traces[trace_id] = [span]
            self._active_spans[span.span_id] = span
        return span

    def start_span(self, trace_id: str, name: str, parent_id: str | None = None, tags: dict[str, str] | None = None) -> Span:
        """Start a child span within a trace."""
        span = Span(
            span_id=generate_id("span"),
            trace_id=trace_id,
            name=name,
            parent_id=parent_id,
            tags=tags or {},
        )
        with self._storage_lock:
            if trace_id in self._traces:
                self._traces[trace_id].append(span)
            else:
                self._traces[trace_id] = [span]
            self._active_spans[span.span_id] = span
        return span

    def finish_span(self, span: Span, status: str = "ok", error: str | None = None) -> None:
        """Finish a span."""
        span.finish(status, error)
        with self._storage_lock:
            self._active_spans.pop(span.span_id, None)

    def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        """Get all spans for a trace."""
        with self._storage_lock:
            spans = self._traces.get(trace_id, [])
            return [s.to_dict() for s in spans]

    def get_trace_summary(self, trace_id: str) -> dict[str, Any]:
        """Get summary of a trace."""
        spans = self.get_trace(trace_id)
        if not spans:
            return {"trace_id": trace_id, "found": False}

        total_ms = sum(s["duration_ms"] for s in spans)
        root = spans[0] if spans else {}
        failed = [s for s in spans if s["status"] != "ok"]

        return {
            "trace_id": trace_id,
            "total_spans": len(spans),
            "total_duration_ms": round(total_ms, 2),
            "root_span": root.get("name", "?"),
            "status": "error" if failed else "ok",
            "failed_spans": [{"name": s["name"], "error": s["error"]} for s in failed],
            "slowest_span": max(spans, key=lambda s: s["duration_ms"])["name"] if spans else None,
        }

    def get_recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent trace summaries."""
        with self._storage_lock:
            trace_ids = list(self._traces.keys())[-limit:]
        return [self.get_trace_summary(tid) for tid in trace_ids]

    def clear(self) -> None:
        with self._storage_lock:
            self._traces.clear()
            self._active_spans.clear()
