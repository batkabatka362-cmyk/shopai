"""Signal/noise separator — distinguish meaningful change from noise.

forecaster projects; concept_drift_detector spots distribution
shifts. This module answers a sharper question per-observation:
*is this latest number a signal worth acting on, or is it within
the band of normal wobble?*

Approach — Welford rolling μ/σ over a window; classify a new
observation by its z-score:

    |z| < 1   → "normal"      noise
    1 ≤ |z| < 2 → "drift"     worth watching
    |z| ≥ 2   → "signal"      worth acting on

Two-sided (direction tracked separately). Provides both single-
metric and batch evaluation. Pure stdlib, deterministic.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.signal_noise_separator")


Classification = Literal["normal", "drift", "signal"]
Direction = Literal["up", "down", "flat"]


@dataclass
class MetricVerdict:
    metric: str
    value: float
    mean: float
    stdev: float
    z_score: float
    classification: Classification
    direction: Direction
    samples: int
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": round(self.value, 4),
            "mean": round(self.mean, 4),
            "stdev": round(self.stdev, 4),
            "z_score": round(self.z_score, 4),
            "classification": self.classification,
            "direction": self.direction,
            "samples": self.samples,
            "note": self.note,
        }


@dataclass
class _Series:
    window: Deque[float]
    # Running Welford stats over the current window
    mean: float = 0.0
    m2: float = 0.0

    @property
    def n(self) -> int:
        return len(self.window)

    @property
    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0

    @property
    def stdev(self) -> float:
        return math.sqrt(self.variance)


class SignalNoiseSeparator:
    def __init__(
        self,
        *,
        window: int = 30,
        drift_threshold: float = 1.0,
        signal_threshold: float = 2.0,
        min_samples: int = 5,
    ) -> None:
        if window < 3:
            raise ValueError("window must be ≥ 3")
        if not 0 < drift_threshold <= signal_threshold:
            raise ValueError(
                "thresholds must satisfy "
                "0 < drift ≤ signal",
            )
        if min_samples < 2:
            raise ValueError("min_samples must be ≥ 2")
        self._window = int(window)
        self._drift_t = float(drift_threshold)
        self._signal_t = float(signal_threshold)
        self._min_samples = int(min_samples)
        self._series: dict[str, _Series] = {}

    # ── Observation intake ───────────────────────────────

    def observe(
        self,
        metric: str,
        value: float,
    ) -> MetricVerdict:
        if not metric:
            raise ValueError("metric required")
        series = self._series.get(metric)
        if series is None:
            series = _Series(
                window=deque(maxlen=self._window),
            )
            self._series[metric] = series

        # Capture stats BEFORE including the new value so the verdict
        # compares against history, not a shifted distribution.
        baseline_mean = series.mean
        baseline_stdev = series.stdev
        samples_before = series.n
        if samples_before >= self._min_samples and baseline_stdev > 0:
            z = (float(value) - baseline_mean) / baseline_stdev
        else:
            z = 0.0

        # Now append the new value + update running stats (Welford).
        self._update_series(series, float(value))

        classification, note = self._classify(
            z, samples_before,
        )
        direction = self._direction(float(value), baseline_mean)
        return MetricVerdict(
            metric=metric,
            value=float(value),
            mean=baseline_mean,
            stdev=baseline_stdev,
            z_score=z,
            classification=classification,
            direction=direction,
            samples=samples_before,
            note=note,
        )

    # ── Batch intake ─────────────────────────────────────

    def observe_batch(
        self,
        metric: str,
        values: Iterable[float],
    ) -> list[MetricVerdict]:
        return [self.observe(metric, v) for v in values]

    # ── Helpers ──────────────────────────────────────────

    def _update_series(
        self, series: _Series, value: float,
    ) -> None:
        # If window is full, remove the oldest from the Welford accumulator
        # before replacing. Since Welford doesn't natively support
        # sliding deletion, recompute on eviction.
        if len(series.window) >= self._window:
            evicted = series.window[0]
            series.window.append(value)
            # Recompute from the surviving window (simple + robust)
            n = 0
            mean = 0.0
            m2 = 0.0
            for x in series.window:
                n += 1
                delta = x - mean
                mean += delta / n
                delta2 = x - mean
                m2 += delta * delta2
            series.mean = mean
            series.m2 = m2
            _ = evicted  # silence unused
            return
        series.window.append(value)
        n = series.n
        delta = value - series.mean
        series.mean += delta / n
        delta2 = value - series.mean
        series.m2 += delta * delta2

    def _classify(
        self, z: float, samples_before: int,
    ) -> tuple[Classification, str]:
        if samples_before < self._min_samples:
            return "normal", (
                f"cold start ({samples_before} < "
                f"{self._min_samples} prior samples)"
            )
        az = abs(z)
        if az >= self._signal_t:
            return "signal", f"|z|={az:.2f} ≥ {self._signal_t}"
        if az >= self._drift_t:
            return "drift", f"|z|={az:.2f} ≥ {self._drift_t}"
        return "normal", f"|z|={az:.2f} < {self._drift_t}"

    def _direction(
        self, value: float, mean: float,
    ) -> Direction:
        if value > mean:
            return "up"
        if value < mean:
            return "down"
        return "flat"

    # ── Query ────────────────────────────────────────────

    def summary(self, metric: str) -> dict[str, Any] | None:
        series = self._series.get(metric)
        if series is None or series.n == 0:
            return None
        return {
            "metric": metric,
            "samples": series.n,
            "mean": round(series.mean, 4),
            "stdev": round(series.stdev, 4),
            "min": min(series.window),
            "max": max(series.window),
        }

    def reset(self, metric: str | None = None) -> int:
        if metric is None:
            n = len(self._series)
            self._series.clear()
            return n
        return 1 if self._series.pop(metric, None) is not None else 0

    def stats(self) -> dict[str, Any]:
        return {
            "metrics_tracked": len(self._series),
            "window": self._window,
            "drift_threshold": self._drift_t,
            "signal_threshold": self._signal_t,
        }
