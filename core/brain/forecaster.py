"""Forecaster — short-term KPI projection from rolling stats + trend.

learning_curve tells us whether a subsystem is improving. forecaster
answers a different question: *"what will my roas be in 7 days?"*
Small, fast, no ML-library dependency. Three deterministic methods
combine into one projection with uncertainty:

  • trend     — linear fit on the recent window, projected forward
  • ema       — exponentially weighted mean for the anchor point
  • seasonal  — subtract the rolling mean of the same weekday/hour
                  slot so Friday spikes don't look like drift

The projection has a ±1-σ band derived from the residual variance
of the linear fit over the window.

API:

    f = Forecaster()
    for ts, value in ts_value_pairs:
        f.observe("roas", value, ts=ts)
    projection = f.forecast("roas", horizon_steps=7)
    # → {value, lower, upper, method, anchor, trend_slope}

Pure stdlib, in-memory rolling buffer.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque


@dataclass
class ObservationPoint:
    ts: float
    value: float


@dataclass
class Projection:
    kpi: str
    horizon_steps: int
    value: float
    lower: float
    upper: float
    anchor: float
    trend_slope: float
    n_samples: int
    method: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "horizon_steps": self.horizon_steps,
            "value": round(self.value, 4),
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "anchor": round(self.anchor, 4),
            "trend_slope": round(self.trend_slope, 6),
            "n_samples": self.n_samples,
            "method": self.method,
        }


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, residual_std_dev). Works on ≥ 2 points."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0, my, 0.0
    slope = num / den
    intercept = my - slope * mx
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    var = (
        sum(r * r for r in residuals) / max(1, n - 2)
    )
    return slope, intercept, math.sqrt(max(0.0, var))


class Forecaster:
    def __init__(
        self,
        *,
        window: int = 50,
        ema_alpha: float = 0.3,
    ) -> None:
        if window < 3:
            raise ValueError("window must be ≥ 3")
        if not 0 < ema_alpha <= 1:
            raise ValueError("ema_alpha must be in (0, 1]")
        self._window = int(window)
        self._ema_alpha = float(ema_alpha)
        self._series: dict[str, Deque[ObservationPoint]] = {}

    # ── Intake ────────────────────────────────────────────

    def observe(
        self, kpi: str, value: float,
        *, ts: float | None = None,
    ) -> None:
        if not kpi:
            raise ValueError("kpi required")
        buf = self._series.setdefault(
            kpi, deque(maxlen=self._window),
        )
        buf.append(ObservationPoint(
            ts=float(ts if ts is not None else time.time()),
            value=float(value),
        ))

    def reset(self, kpi: str | None = None) -> int:
        if kpi is None:
            n = sum(len(b) for b in self._series.values())
            self._series.clear()
            return n
        buf = self._series.pop(kpi, deque())
        return len(buf)

    # ── Projections ──────────────────────────────────────

    def _ema(self, values: list[float]) -> float:
        if not values:
            return 0.0
        ema = values[0]
        for v in values[1:]:
            ema = self._ema_alpha * v + (1 - self._ema_alpha) * ema
        return ema

    def forecast(
        self, kpi: str,
        horizon_steps: int = 1,
    ) -> Projection:
        if horizon_steps < 1:
            raise ValueError("horizon_steps must be ≥ 1")
        buf = list(self._series.get(kpi, ()))
        n = len(buf)
        if n == 0:
            return Projection(
                kpi=kpi, horizon_steps=horizon_steps,
                value=0.0, lower=0.0, upper=0.0,
                anchor=0.0, trend_slope=0.0,
                n_samples=0, method="empty",
            )
        values = [p.value for p in buf]
        anchor = self._ema(values)
        if n < 3:
            # Not enough data for trend → flatline at anchor
            return Projection(
                kpi=kpi, horizon_steps=horizon_steps,
                value=anchor, lower=anchor, upper=anchor,
                anchor=anchor, trend_slope=0.0,
                n_samples=n, method="ema_flatline",
            )
        # Use position index (0..n-1) as x so seasonal / irregular
        # timestamps don't distort the slope.
        xs = [float(i) for i in range(n)]
        slope, intercept, resid = _linear_fit(xs, values)
        # Anchor = fitted value at the last step, then project forward
        at_last = slope * (n - 1) + intercept
        projected = slope * (n - 1 + horizon_steps) + intercept
        # Blend with EMA anchor so one outlier doesn't yank the value.
        blended = 0.5 * projected + 0.5 * (
            anchor + slope * horizon_steps
        )
        half = 1.96 * resid
        return Projection(
            kpi=kpi, horizon_steps=horizon_steps,
            value=blended,
            lower=blended - half, upper=blended + half,
            anchor=at_last, trend_slope=slope,
            n_samples=n, method="trend+ema",
        )

    # ── Seasonality helper (optional) ────────────────────

    def deseasonalise(
        self,
        kpi: str,
        *,
        bucket_key: str = "hour",
    ) -> list[float]:
        """Return the series with the per-bucket mean removed. bucket_key
        is ``"hour"`` (0..23) or ``"dow"`` (0..6). Small-buffer friendly —
        buckets with < 2 samples are left alone."""
        buf = list(self._series.get(kpi, ()))
        if not buf:
            return []
        buckets: dict[int, list[float]] = {}
        for p in buf:
            t = time.gmtime(p.ts)
            key = t.tm_hour if bucket_key == "hour" else t.tm_wday
            buckets.setdefault(key, []).append(p.value)
        means = {
            k: sum(v) / len(v)
            for k, v in buckets.items() if len(v) >= 2
        }
        out: list[float] = []
        for p in buf:
            t = time.gmtime(p.ts)
            key = t.tm_hour if bucket_key == "hour" else t.tm_wday
            out.append(p.value - means.get(key, 0.0))
        return out

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "kpis": sorted(self._series.keys()),
            "samples": {
                k: len(v) for k, v in self._series.items()
            },
            "window": self._window,
        }
