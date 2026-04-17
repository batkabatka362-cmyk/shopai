"""Per-caller cost trajectory forecaster — Upgrade 3.

The cost ledger (Option Z) tells operators WHAT was spent; the
budget enforcer (Option T) tells them when a hard cap is hit.
Neither answers the question "at the current burn rate, will
this caller blow past its monthly budget?" until it's already
too late.

``CostForecaster`` bridges that gap. It periodically samples the
per-caller totals from ``CostLedger``, computes a rolling burn
rate over a configurable window, and projects forward to any
horizon (1 hour, 24 hours, 30 days). The result is a small
JSON-safe structure the reliability collector can embed and the
dashboard can render as a "projected spend" column.

Why a separate module instead of extending CostLedger?
------------------------------------------------------

* The ledger is on the hot router path and must stay as cheap
  as possible. Forecasting involves ring buffers, regression,
  and linear algebra — all of which belong on the telemetry
  side, not the per-call write side.
* A forecast is only useful if the horizon is configurable
  per call. Bundling it into the ledger would force one
  fixed horizon onto every downstream consumer.
* Testing stays simpler — we can swap in a fake clock and a
  chosen ledger shape without touching the production ledger.

Design rules:

* Bounded ring. Samples are kept in a ``deque(maxlen=N)`` so
  memory stays flat across a multi-day run.
* Minimum-samples floor. The forecaster refuses to project
  from a single sample (the first one has no slope); it
  returns ``None`` in that case and the caller decides whether
  to display "no forecast yet" or fall back to the raw total.
* Self-protective math. Negative burn rates (ledger reset, or
  a caller tag folded into overflow) are clamped to 0.
* Never raises on the hot path. Sample failures log-and-return.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger

logger = get_logger("adapters.cost_forecast")


# ── Config ──────────────────────────────────────────────────

_DEFAULT_WINDOW_MAX = 120          # keep last 120 samples
_DEFAULT_WINDOW_SEC = 3600.0        # use ~1h of data for the slope
_DEFAULT_MIN_SAMPLES = 2            # need at least 2 to draw a line
_DEFAULT_SPIKE_RATIO = 2.0          # "spike" = burn rate >= 2× baseline
# ``baseline`` for a spike is the burn rate over the FULL history
# (or a caller-provided monthly-budget fraction); ``current`` is
# the short-window burn rate. A ratio >= 2.0 fires an alert.


# ── Sample / forecast types ─────────────────────────────────


@dataclass
class _Sample:
    ts: float
    per_caller_usd: dict[str, float]
    total_usd: float


@dataclass
class CallerForecast:
    caller: str
    current_usd: float
    burn_rate_usd_per_hour: float
    projected_usd: float       # current_usd + burn_rate * horizon_hours
    horizon_hours: float
    spike_ratio: float          # short window burn ÷ long window burn
    is_spike: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "current_usd": round(self.current_usd, 6),
            "burn_rate_usd_per_hour": round(
                self.burn_rate_usd_per_hour, 6,
            ),
            "projected_usd": round(self.projected_usd, 6),
            "horizon_hours": self.horizon_hours,
            "spike_ratio": round(self.spike_ratio, 3),
            "is_spike": self.is_spike,
        }


@dataclass
class ForecastReport:
    timestamp: float
    horizon_hours: float
    samples: int
    window_coverage_sec: float
    per_caller: list[CallerForecast] = field(default_factory=list)
    spikes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "horizon_hours": self.horizon_hours,
            "samples": self.samples,
            "window_coverage_sec": round(self.window_coverage_sec, 1),
            "per_caller": [f.to_dict() for f in self.per_caller],
            "spikes": list(self.spikes),
        }


# ── Forecaster ─────────────────────────────────────────────


class CostForecaster:
    """Thread-safe per-caller cost trajectory forecaster.

    Usage pattern::

        f = get_cost_forecaster()
        f.sample()                   # from controller cycle
        report = f.forecast(horizon_hours=24)
    """

    def __init__(
        self,
        *,
        max_samples: int = _DEFAULT_WINDOW_MAX,
        window_sec: float = _DEFAULT_WINDOW_SEC,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
        spike_ratio: float = _DEFAULT_SPIKE_RATIO,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_samples < 2:
            raise ValueError("max_samples must be >= 2")
        if window_sec <= 0:
            raise ValueError("window_sec must be positive")
        if min_samples < 2:
            raise ValueError("min_samples must be >= 2")
        self._samples: deque[_Sample] = deque(maxlen=max_samples)
        self._window_sec = float(window_sec)
        self._min_samples = int(min_samples)
        self._spike_ratio = float(spike_ratio)
        self._clock = clock
        self._lock = threading.RLock()
        self._sample_failures = 0

    # ── Sampling ────────────────────────────────────────────

    def sample(self) -> bool:
        """Record one sample from the cost ledger.

        Returns True on success, False on defensive failure.
        Never raises — the forecaster must never break the
        controller's cycle.
        """
        try:
            from core.adapters.cost_ledger import get_cost_ledger
            ledger = get_cost_ledger()
        except Exception as exc:  # noqa: BLE001
            logger.debug("forecast: ledger import failed: %s", exc)
            with self._lock:
                self._sample_failures += 1
            return False

        try:
            total = float(ledger.total_usd())
            callers = ledger.per_caller()
        except Exception as exc:  # noqa: BLE001
            logger.debug("forecast: ledger read failed: %s", exc)
            with self._lock:
                self._sample_failures += 1
            return False

        per_caller: dict[str, float] = {}
        for row in callers or []:
            name = str(row.get("caller") or "").strip()
            if not name:
                continue
            try:
                per_caller[name] = float(row.get("total_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue

        now = self._clock()
        sample = _Sample(
            ts=now, per_caller_usd=per_caller, total_usd=total,
        )
        with self._lock:
            self._samples.append(sample)
        return True

    # ── Forecasting ─────────────────────────────────────────

    def forecast(
        self,
        *,
        horizon_hours: float = 24.0,
        callers: list[str] | None = None,
    ) -> ForecastReport:
        """Project per-caller spend ``horizon_hours`` into the future.

        ``callers`` optionally restricts the report to a subset.
        Unknown callers or callers with fewer than ``min_samples``
        data points are omitted silently.
        """
        if horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")
        now = self._clock()
        with self._lock:
            samples = list(self._samples)

        if len(samples) < self._min_samples:
            return ForecastReport(
                timestamp=now,
                horizon_hours=horizon_hours,
                samples=len(samples),
                window_coverage_sec=0.0,
            )

        # Determine the short-window slice for burn rate.
        cutoff = now - self._window_sec
        window = [s for s in samples if s.ts >= cutoff]
        if len(window) < self._min_samples:
            # Not enough samples in the preferred window — fall
            # back to ALL samples so we still produce a forecast.
            window = samples
        window_coverage = (
            window[-1].ts - window[0].ts if len(window) >= 2 else 0.0
        )

        # Union of callers across both long and short windows
        # (so a caller that dropped out of recent samples still
        # shows a cumulative figure of zero burn rate).
        all_callers: set[str] = set()
        for s in samples:
            all_callers.update(s.per_caller_usd.keys())
        if callers is not None:
            wanted = {c for c in callers if c in all_callers}
        else:
            wanted = all_callers

        forecasts: list[CallerForecast] = []
        spikes: list[str] = []
        for caller in sorted(wanted):
            current = window[-1].per_caller_usd.get(caller, 0.0)
            # Short-window burn rate = (last - first) / (dt_hours).
            short_dt_hr = (
                (window[-1].ts - window[0].ts) / 3600.0
                if len(window) >= 2 else 0.0
            )
            if short_dt_hr <= 0:
                continue
            short_delta = (
                window[-1].per_caller_usd.get(caller, 0.0)
                - window[0].per_caller_usd.get(caller, 0.0)
            )
            short_burn = max(0.0, short_delta / short_dt_hr)

            # Long-window burn for the spike ratio. We anchor on
            # the caller's FIRST APPEARANCE in the sample history,
            # not on the oldest absolute sample — otherwise every
            # caller who joined mid-stream would look like an
            # infinite spike (because the first absolute sample
            # had them at 0 by definition). The first-appearance
            # anchor means "spike" = "this caller's recent burn
            # is unusually high for them".
            first_seen_idx: int | None = None
            for i, s in enumerate(samples):
                if caller in s.per_caller_usd:
                    first_seen_idx = i
                    break
            if first_seen_idx is None:
                continue
            first_seen_sample = samples[first_seen_idx]
            long_dt_hr = (
                (samples[-1].ts - first_seen_sample.ts) / 3600.0
            )
            if long_dt_hr > 0:
                long_delta = (
                    samples[-1].per_caller_usd.get(caller, 0.0)
                    - first_seen_sample.per_caller_usd.get(caller, 0.0)
                )
                long_burn = max(0.0, long_delta / long_dt_hr)
            else:
                long_burn = short_burn

            # Spike ratio: short ÷ long. A young series where
            # long_burn is ~0 trips this trivially; guard with a
            # min-denominator so "warmup" doesn't fire every time.
            # Also require the caller's long-window coverage to
            # exceed the short-window coverage × 2 before we
            # trust the ratio — otherwise the two windows measure
            # the same data and the ratio is meaningless.
            has_baseline = long_dt_hr >= short_dt_hr * 2.0
            ratio = (
                short_burn / long_burn
                if long_burn >= 1e-9 and has_baseline
                else 1.0
            )
            is_spike = (
                has_baseline
                and ratio >= self._spike_ratio
                and short_burn > 0.0
            )

            projected = current + short_burn * horizon_hours
            forecasts.append(CallerForecast(
                caller=caller,
                current_usd=current,
                burn_rate_usd_per_hour=short_burn,
                projected_usd=projected,
                horizon_hours=horizon_hours,
                spike_ratio=ratio,
                is_spike=is_spike,
            ))
            if is_spike:
                spikes.append(caller)

        # Sort by projected spend descending — operators want the
        # biggest risks at the top.
        forecasts.sort(key=lambda f: -f.projected_usd)
        return ForecastReport(
            timestamp=now,
            horizon_hours=horizon_hours,
            samples=len(samples),
            window_coverage_sec=window_coverage,
            per_caller=forecasts,
            spikes=sorted(spikes),
        )

    # ── Snapshot & admin ────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "samples": len(self._samples),
                "max_samples": self._samples.maxlen,
                "window_sec": self._window_sec,
                "min_samples": self._min_samples,
                "spike_ratio": self._spike_ratio,
                "sample_failures": self._sample_failures,
                "oldest_ts": (
                    self._samples[0].ts if self._samples else 0.0
                ),
                "newest_ts": (
                    self._samples[-1].ts if self._samples else 0.0
                ),
            }

    def reset(self) -> None:
        """Test helper — clear samples + counters."""
        with self._lock:
            self._samples.clear()
            self._sample_failures = 0


# ── Singleton ────────────────────────────────────────────

_default_forecaster: CostForecaster | None = None
_default_lock = threading.Lock()


def get_cost_forecaster() -> CostForecaster:
    global _default_forecaster
    if _default_forecaster is None:
        with _default_lock:
            if _default_forecaster is None:
                _default_forecaster = CostForecaster()
    return _default_forecaster


def reset_cost_forecaster() -> None:
    """Test helper — drop the singleton."""
    global _default_forecaster
    with _default_lock:
        _default_forecaster = None
