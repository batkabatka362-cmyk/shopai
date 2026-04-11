"""MetricsCollector — collects and aggregates system metrics.

Wave 2 #6 extends this module with :class:`SLATracker`, a
rolling-window per-subsystem health monitor. The existing
``MetricsCollector`` is kept exactly as-is (backwards
compatibility with everything that already calls
``increment`` / ``gauge`` / ``histogram``). ``SLATracker`` sits
next to it, consuming the same sort of numbers but aggregated
by subsystem so operators can see "is *this* subsystem within
its target?" rather than scrolling through a flat histogram.

A :class:`MetricsCollector` instance exposes
:meth:`get_sla_tracker` so the singleton can be shared across
callers without anyone having to pass a new dependency
through.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


class MetricsCollector:
    """Thread-safe metrics collection with aggregation."""

    _instance: MetricsCollector | None = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> MetricsCollector:
        with cls._lock_cls:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        # Wave 2 #6 — lazily constructed so importing the
        # collector in places that never touch SLAs has no
        # surprise cost.
        self._sla: SLATracker | None = None

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def histogram(self, name: str, value: float) -> None:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            if len(self._histograms[name]) > 10000:
                self._histograms[name] = self._histograms[name][-10000:]

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        with self._lock:
            return self._gauges.get(name, 0.0)

    def get_histogram_stats(self, name: str) -> dict[str, float]:
        with self._lock:
            values = list(self._histograms.get(name, []))
        if not values:
            return {"count": 0}
        values.sort()
        n = len(values)
        return {
            "count": n,
            "min": round(values[0], 4),
            "max": round(values[-1], 4),
            "avg": round(sum(values) / n, 4),
            "p50": round(values[n // 2], 4),
            "p95": round(values[int(n * 0.95)], 4),
            "p99": round(values[int(n * 0.99)], 4),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: self.get_histogram_stats(k) for k in self._histograms},
            }

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()

    # ── SLA tracker (Wave 2 #6) ──────────────────────────────

    def get_sla_tracker(self) -> SLATracker:
        """Return the shared :class:`SLATracker` instance.

        Lazily constructed on first use so callers that never
        touch SLAs don't pay the cost. Thread-safe: the
        first-time construction is guarded by the collector's
        own lock.
        """
        with self._lock:
            if self._sla is None:
                self._sla = SLATracker.from_env()
            return self._sla

    def get_sla_report(
        self, subsystem: str | None = None,
    ) -> dict[str, Any]:
        """Return the SLA report for *subsystem* or all tracked.

        Shortcut for ``get_sla_tracker().get_report(subsystem)``
        so callers with a collector reference don't need to
        grab the tracker explicitly.
        """
        return self.get_sla_tracker().get_report(subsystem)


# ---------------------------------------------------------------------------
# SLA tracker — Wave 2 #6
# ---------------------------------------------------------------------------


# SLA status thresholds. A subsystem is:
#   * ``"ok"``       — meets every target
#   * ``"degraded"`` — within the "warning" band around any target
#   * ``"breached"`` — below target on any dimension
_DEGRADED_MARGIN = 0.1  # 10% of headroom


@dataclass
class SLAThresholds:
    """Per-subsystem SLA targets.

    All fields default to values that won't flag anything as
    degraded — callers (or :meth:`SLATracker.from_env`) can
    tighten them. A field set to ``None`` opts out of that
    dimension entirely, so a subsystem can track only latency
    or only cost without having to fake a success rate.
    """

    min_success_rate:   float | None = 0.95
    max_p95_latency_ms: float | None = 1_000.0
    max_cost_per_call:  float | None = 0.01


@dataclass
class SLASample:
    """A single observation feeding the rolling window."""

    success:    bool
    latency_ms: float
    cost:       float
    ts:         float = field(default_factory=time.time)


class SLATracker:
    """Rolling-window per-subsystem SLA health monitor.

    Each subsystem owns a fixed-size deque of recent samples.
    Queries compute success rate, p95 latency, and mean
    cost-per-call from the window, then compare against the
    configured :class:`SLAThresholds` (per-subsystem overrides
    fall back to a default that can be loaded from environment
    variables).

    Design notes
    ------------
    * **Rolling window, not time window.** Fixed-count is
      cheaper (no timestamp scans) and deterministic for
      tests. If a subsystem is idle the window stays "last
      N calls" which is exactly what SLAs care about anyway.
    * **p95 via nearest-rank on sorted copy.** No numpy; the
      window is small enough that ``sorted()`` is fine.
    * **Thread-safe.** A single RLock guards all state so the
      tracker can be called from the brain worker pool and
      the telemetry sweeper without races.
    """

    def __init__(
        self,
        *,
        window_size: int = 500,
        default_thresholds: SLAThresholds | None = None,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self._window_size = window_size
        self._default = default_thresholds or SLAThresholds()
        self._lock = threading.RLock()
        self._samples: dict[str, deque[SLASample]] = defaultdict(
            lambda: deque(maxlen=window_size),
        )
        self._thresholds: dict[str, SLAThresholds] = {}

    # -- env loading ------------------------------------------------

    @classmethod
    def from_env(cls, **kwargs: Any) -> SLATracker:
        """Construct an SLATracker with defaults sourced from env.

        Environment variables:

        * ``SHOPAI_SLA_WINDOW_SIZE``
        * ``SHOPAI_SLA_MIN_SUCCESS_RATE``
        * ``SHOPAI_SLA_MAX_P95_LATENCY_MS``
        * ``SHOPAI_SLA_MAX_COST_PER_CALL``

        Any variable left unset uses the class default. Values
        that fail to parse are logged and ignored (tracker falls
        back to the default for that field).
        """
        def _f(name: str) -> float | None:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        def _i(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        defaults = SLAThresholds()
        thresholds = SLAThresholds(
            min_success_rate=(
                _f("SHOPAI_SLA_MIN_SUCCESS_RATE")
                if _f("SHOPAI_SLA_MIN_SUCCESS_RATE") is not None
                else defaults.min_success_rate
            ),
            max_p95_latency_ms=(
                _f("SHOPAI_SLA_MAX_P95_LATENCY_MS")
                if _f("SHOPAI_SLA_MAX_P95_LATENCY_MS") is not None
                else defaults.max_p95_latency_ms
            ),
            max_cost_per_call=(
                _f("SHOPAI_SLA_MAX_COST_PER_CALL")
                if _f("SHOPAI_SLA_MAX_COST_PER_CALL") is not None
                else defaults.max_cost_per_call
            ),
        )
        return cls(
            window_size=_i("SHOPAI_SLA_WINDOW_SIZE", 500),
            default_thresholds=thresholds,
            **kwargs,
        )

    # -- mutation ---------------------------------------------------

    def set_thresholds(
        self, subsystem: str, thresholds: SLAThresholds,
    ) -> None:
        """Override the SLA targets for a single subsystem.

        The default thresholds stay put — this call just adds
        an override that takes precedence when computing the
        subsystem's report.
        """
        with self._lock:
            self._thresholds[subsystem] = thresholds

    def record(
        self,
        subsystem: str,
        *,
        success: bool,
        latency_ms: float,
        cost: float = 0.0,
        ts: float | None = None,
    ) -> None:
        """Append a single observation to the subsystem window."""
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if cost < 0:
            raise ValueError("cost must be non-negative")
        sample = SLASample(
            success=bool(success),
            latency_ms=float(latency_ms),
            cost=float(cost),
            ts=ts if ts is not None else time.time(),
        )
        with self._lock:
            self._samples[subsystem].append(sample)

    def reset(self, subsystem: str | None = None) -> None:
        """Drop the window for *subsystem* or for everything."""
        with self._lock:
            if subsystem is None:
                self._samples.clear()
            else:
                self._samples.pop(subsystem, None)

    # -- reporting --------------------------------------------------

    def _thresholds_for(self, subsystem: str) -> SLAThresholds:
        return self._thresholds.get(subsystem, self._default)

    @staticmethod
    def _p95(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        # Nearest-rank p95 (index = ceil(0.95 * n) - 1)
        idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
        return ordered[idx]

    def get_report(
        self, subsystem: str | None = None,
    ) -> dict[str, Any]:
        """Return the rolling-window SLA report.

        When *subsystem* is ``None`` the report covers every
        subsystem with at least one sample; otherwise it's a
        single-subsystem dict. Shape::

            {
              "subsystem": "brain",
              "samples": 120,
              "success_rate": 0.98,
              "p95_latency_ms": 842.5,
              "mean_cost_per_call": 0.0031,
              "thresholds": {...},
              "status": "ok" | "degraded" | "breached",
              "breaches": ["p95_latency_ms", ...],
            }
        """
        with self._lock:
            if subsystem is not None:
                return self._report_one(subsystem)
            return {
                "subsystems": {
                    name: self._report_one(name)
                    for name in sorted(self._samples.keys())
                },
                "total_subsystems": len(self._samples),
            }

    def _report_one(self, subsystem: str) -> dict[str, Any]:
        samples = list(self._samples.get(subsystem, ()))
        thr = self._thresholds_for(subsystem)
        if not samples:
            return {
                "subsystem":           subsystem,
                "samples":             0,
                "success_rate":        None,
                "p95_latency_ms":      None,
                "mean_cost_per_call":  None,
                "thresholds":          _thresholds_dict(thr),
                "status":              "unknown",
                "breaches":            [],
            }
        n = len(samples)
        successes = sum(1 for s in samples if s.success)
        success_rate = successes / n
        p95_latency = self._p95([s.latency_ms for s in samples])
        mean_cost = sum(s.cost for s in samples) / n

        breaches: list[str] = []
        warnings: list[str] = []

        if thr.min_success_rate is not None:
            if success_rate < thr.min_success_rate:
                breaches.append("success_rate")
            elif success_rate < thr.min_success_rate + (
                _DEGRADED_MARGIN * (1 - thr.min_success_rate)
            ):
                warnings.append("success_rate")

        if thr.max_p95_latency_ms is not None:
            if p95_latency > thr.max_p95_latency_ms:
                breaches.append("p95_latency_ms")
            elif p95_latency > thr.max_p95_latency_ms * (1 - _DEGRADED_MARGIN):
                warnings.append("p95_latency_ms")

        if thr.max_cost_per_call is not None:
            if mean_cost > thr.max_cost_per_call:
                breaches.append("mean_cost_per_call")
            elif mean_cost > thr.max_cost_per_call * (1 - _DEGRADED_MARGIN):
                warnings.append("mean_cost_per_call")

        if breaches:
            status = "breached"
        elif warnings:
            status = "degraded"
        else:
            status = "ok"

        return {
            "subsystem":           subsystem,
            "samples":             n,
            "success_rate":        success_rate,
            "p95_latency_ms":      p95_latency,
            "mean_cost_per_call":  mean_cost,
            "thresholds":          _thresholds_dict(thr),
            "status":              status,
            "breaches":            breaches,
            "warnings":            warnings,
        }

    def subsystems(self) -> list[str]:
        with self._lock:
            return sorted(self._samples.keys())


def _thresholds_dict(thr: SLAThresholds) -> dict[str, Any]:
    return {
        "min_success_rate":   thr.min_success_rate,
        "max_p95_latency_ms": thr.max_p95_latency_ms,
        "max_cost_per_call":  thr.max_cost_per_call,
    }


__all__ = [
    "MetricsCollector",
    "SLATracker",
    "SLAThresholds",
    "SLASample",
]
