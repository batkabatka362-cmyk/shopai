"""Per-adapter usage metrics.

Tracks every ``execute()`` call so the smart router can:

* enforce free-tier daily / monthly quotas (e.g. Gemini 1000
  req/day) before they bite us with a 429
* compute p50 / p95 / p99 latency for SLO-driven routing
* roll up running cost in USD across vendors
* surface health (success rate, last error) on the operator
  dashboard

The metrics layer is **fail-soft**: a bug in the metrics code
must never crash a real adapter call. Every method that touches
the counters wraps the inner write in ``try/except`` and logs
the failure instead of propagating it.

Quotas reset on a wall-clock boundary (UTC midnight for daily,
first-of-month for monthly). The reset check happens on every
read so a long-running process doesn't carry yesterday's count
into today.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("adapters.metrics")


# ── Per-adapter rolling stats ──────────────────────────────────


@dataclass
class AdapterMetrics:
    """Mutable counter set for one adapter.

    Stored inside ``MetricsCollector._stats`` keyed by adapter
    name. Reads/writes happen under the collector lock — never
    touch this directly from outside the collector.
    """

    name: str
    calls_total: int = 0
    calls_success: int = 0
    calls_failure: int = 0
    cost_usd_total: float = 0.0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    latency_samples: list[float] = field(default_factory=list)
    last_error: str = ""
    last_error_at: float = 0.0
    last_call_at: float = 0.0

    # Quota counters — reset on day / month boundary
    daily_calls: int = 0
    daily_reset_epoch: float = 0.0
    monthly_calls: int = 0
    monthly_reset_epoch: float = 0.0

    def success_rate(self) -> float:
        if self.calls_total == 0:
            return 1.0
        return round(self.calls_success / self.calls_total, 4)

    def percentile(self, pct: int) -> float:
        """Return the *pct* percentile latency in milliseconds.

        Uses the in-memory rolling sample window
        (``MetricsCollector._sample_cap`` last calls). Returns 0
        for an empty window.
        """
        if not self.latency_samples:
            return 0.0
        sorted_samples = sorted(self.latency_samples)
        idx = max(0, min(len(sorted_samples) - 1,
                          int(len(sorted_samples) * pct / 100)))
        return round(sorted_samples[idx], 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "calls_total": self.calls_total,
            "calls_success": self.calls_success,
            "calls_failure": self.calls_failure,
            "success_rate": self.success_rate(),
            "cost_usd_total": round(self.cost_usd_total, 4),
            "tokens_in_total": self.tokens_in_total,
            "tokens_out_total": self.tokens_out_total,
            "latency_p50_ms": self.percentile(50),
            "latency_p95_ms": self.percentile(95),
            "latency_p99_ms": self.percentile(99),
            "daily_calls": self.daily_calls,
            "monthly_calls": self.monthly_calls,
            "last_error": self.last_error,
            "last_call_at": self.last_call_at,
        }


# ── Collector ──────────────────────────────────────────────────


_DAY_SECONDS = 24 * 60 * 60
_MONTH_SECONDS = 30 * _DAY_SECONDS


class MetricsCollector:
    """Process-wide adapter metrics aggregator.

    Single ``RLock`` protects every counter. Reads (``stats_for``,
    ``snapshot``) take the lock briefly to copy the data so
    callers do not hold the lock during downstream work.
    """

    def __init__(self, sample_cap: int = 256) -> None:
        self._lock = threading.RLock()
        self._stats: dict[str, AdapterMetrics] = {}
        self._sample_cap = sample_cap

    # ── Recording ──────────────────────────────────────────────

    def record(
        self,
        adapter: str,
        *,
        success: bool,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error: str = "",
    ) -> None:
        """Capture one ``AdapterResult`` worth of stats.

        Fail-soft: any exception inside this method is caught and
        logged but never propagated — a metrics bug must not
        break the real call path.
        """
        try:
            with self._lock:
                m = self._stats.get(adapter)
                if m is None:
                    m = AdapterMetrics(name=adapter)
                    self._stats[adapter] = m

                self._refresh_quota_windows(m)

                m.calls_total += 1
                m.last_call_at = time.time()
                m.daily_calls += 1
                m.monthly_calls += 1

                if success:
                    m.calls_success += 1
                else:
                    m.calls_failure += 1
                    if error:
                        m.last_error = error[:200]
                        m.last_error_at = time.time()

                if cost_usd:
                    m.cost_usd_total += float(cost_usd)
                if tokens_in:
                    m.tokens_in_total += int(tokens_in)
                if tokens_out:
                    m.tokens_out_total += int(tokens_out)

                if latency_ms:
                    m.latency_samples.append(float(latency_ms))
                    # Keep window bounded so memory doesn't grow
                    if len(m.latency_samples) > self._sample_cap:
                        m.latency_samples = m.latency_samples[-self._sample_cap:]
        except Exception as exc:  # noqa: BLE001
            logger.debug("metrics.record failed for %s: %s", adapter, exc)

        # Wave 3 #4: mirror the sample into the telemetry SLA
        # tracker so operators get per-adapter rolling health
        # ("ok" / "degraded" / "breached") without having to run
        # a second instrumentation pass. Fail-soft — an SLA
        # tracker import/record failure must not bubble up into
        # the real call path.
        try:
            self._feed_sla_tracker(
                adapter=adapter,
                success=bool(success),
                latency_ms=float(latency_ms or 0.0),
                cost=float(cost_usd or 0.0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("metrics.record → SLA feed failed: %s", exc)

    def _feed_sla_tracker(
        self,
        *,
        adapter: str,
        success: bool,
        latency_ms: float,
        cost: float,
    ) -> None:
        """Forward one call sample into the shared SLATracker.

        Lazy-imports the telemetry collector so a teardown that
        drops the telemetry module (deployment variants without
        SLA) still leaves this metrics collector functional.
        Isolated in its own method so the caller can catch any
        failure cleanly regardless of whether the import or the
        record() call blew up.
        """
        from core.telemetry.metrics_collector import MetricsCollector as _TM
        tracker = _TM().get_sla_tracker()
        tracker.record(
            adapter,
            success=success,
            latency_ms=latency_ms,
            cost=cost,
        )

    def get_sla_report(
        self, adapter: str | None = None,
    ) -> dict[str, Any]:
        """Return the SLA report for *adapter* or every adapter.

        Convenience forwarder to the shared SLATracker. Returns
        an empty dict if the telemetry module isn't importable
        so production callers can always invoke this without
        branching on deployment variant.
        """
        try:
            from core.telemetry.metrics_collector import MetricsCollector as _TM
            return _TM().get_sla_tracker().get_report(adapter)
        except Exception as exc:  # noqa: BLE001
            logger.debug("metrics.get_sla_report failed: %s", exc)
            return {}

    def _refresh_quota_windows(self, m: AdapterMetrics) -> None:
        """Reset daily/monthly counters when the wall clock
        rolls over. Called inside the lock by ``record()`` and
        ``stats_for()``.

        UTC-based to avoid DST edge cases.
        """
        now = time.time()
        if now >= m.daily_reset_epoch:
            m.daily_calls = 0
            m.daily_reset_epoch = now + _DAY_SECONDS
        if now >= m.monthly_reset_epoch:
            m.monthly_calls = 0
            m.monthly_reset_epoch = now + _MONTH_SECONDS

    # ── Reading ────────────────────────────────────────────────

    def stats_for(self, adapter: str) -> dict[str, Any] | None:
        """Return a snapshot dict for one adapter, or ``None`` if
        the adapter has not yet been recorded."""
        with self._lock:
            m = self._stats.get(adapter)
            if m is None:
                return None
            self._refresh_quota_windows(m)
            return m.to_dict()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Snapshot every adapter's stats. Used for the
        ``GET /admin/metrics/adapters`` endpoint."""
        with self._lock:
            result: dict[str, dict[str, Any]] = {}
            for name, m in self._stats.items():
                self._refresh_quota_windows(m)
                result[name] = m.to_dict()
            return result

    def reset(self, adapter: str | None = None) -> None:
        """Forget all stats for *adapter* (or every adapter when
        ``None``). Test helper."""
        with self._lock:
            if adapter is None:
                self._stats.clear()
            else:
                self._stats.pop(adapter, None)

    # ── Quota helpers (router uses these) ─────────────────────

    def quota_used_pct(self, adapter: str, daily_limit: int) -> float:
        """Return the fraction of *daily_limit* the adapter has
        burned today. ``0.0`` if the adapter has no recorded
        calls or ``daily_limit <= 0``."""
        if daily_limit <= 0:
            return 0.0
        with self._lock:
            m = self._stats.get(adapter)
            if m is None:
                return 0.0
            self._refresh_quota_windows(m)
            return min(1.0, m.daily_calls / daily_limit)


# ── Module-level singleton ─────────────────────────────────────


_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_metrics() -> MetricsCollector:
    """Return the process-wide metrics collector singleton."""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector


def reset_metrics() -> None:
    """Replace the singleton with a fresh empty collector
    (test helper)."""
    global _collector
    with _collector_lock:
        _collector = MetricsCollector()
