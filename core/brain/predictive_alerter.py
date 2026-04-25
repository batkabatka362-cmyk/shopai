"""Predictive alerter — warn BEFORE a KPI breaches a threshold.

forecaster projects a KPI forward with uncertainty. Feasibility_gate
and action_safety_guard fire AFTER a threshold is crossed. This
module is the middleman: given a linear-ish trajectory of a KPI and
an owner-set threshold, it predicts when the KPI will cross the
threshold and emits a ``PreBreachAlert`` with:

  • kpi, current_value, threshold, direction (above/below)
  • projected_breach_ts (seconds-from-now; None if never)
  • confidence (0..1 — higher if r² is high)
  • severity: "info" / "warning" / "critical" by how soon

Use cases:
  • "CPM trending up — ROAS projected to breach 1.5 in 4h"
  • "Inventory drop trajectory — stockout in 2 days"

Complements signal_noise_separator (retrospective) and forecaster
(values only — no breach semantics). Pure stdlib, deterministic.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.predictive_alerter")


Direction = Literal["above", "below"]
Severity = Literal["info", "warning", "critical", "none"]


@dataclass
class PreBreachAlert:
    kpi: str
    current_value: float
    threshold: float
    direction: Direction
    projected_breach_s: float | None
    confidence: float
    severity: Severity
    slope: float
    n_samples: int
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "current_value": round(self.current_value, 4),
            "threshold": round(self.threshold, 4),
            "direction": self.direction,
            "projected_breach_s": (
                round(self.projected_breach_s, 1)
                if self.projected_breach_s is not None else None
            ),
            "confidence": round(self.confidence, 4),
            "severity": self.severity,
            "slope": round(self.slope, 6),
            "n_samples": self.n_samples,
            "note": self.note,
        }


@dataclass
class _Series:
    window: Deque[tuple[float, float]]   # (ts, value)


# ── Linear fit helper ────────────────────────────────────

def _linear_fit(
    points: list[tuple[float, float]],
) -> tuple[float, float, float]:
    """Return (slope, intercept, r_squared) on (ts, value) pairs."""
    n = len(points)
    if n < 2:
        return 0.0, points[0][1] if points else 0.0, 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    num = sum((x - mx) * (y - my) for x, y in points)
    den = sum((x - mx) ** 2 for x, _ in points)
    if den == 0:
        return 0.0, my, 0.0
    slope = num / den
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for _, y in points)
    if ss_tot == 0:
        return slope, intercept, 1.0
    ss_res = sum(
        (y - (slope * x + intercept)) ** 2 for x, y in points
    )
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r2


class PredictiveAlerter:
    def __init__(
        self,
        *,
        window: int = 30,
        min_samples: int = 5,
        warning_horizon_s: float = 6 * 3600,
        critical_horizon_s: float = 30 * 60,
    ) -> None:
        if window < 3:
            raise ValueError("window must be ≥ 3")
        if min_samples < 2:
            raise ValueError("min_samples must be ≥ 2")
        if critical_horizon_s >= warning_horizon_s:
            raise ValueError(
                "critical_horizon must be < warning_horizon",
            )
        self._window = int(window)
        self._min_samples = int(min_samples)
        self._warning_horizon = float(warning_horizon_s)
        self._critical_horizon = float(critical_horizon_s)
        self._series: dict[str, _Series] = {}

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        kpi: str,
        value: float,
        *,
        ts: float | None = None,
    ) -> None:
        if not kpi:
            raise ValueError("kpi required")
        series = self._series.setdefault(
            kpi, _Series(window=deque(maxlen=self._window)),
        )
        series.window.append(
            (float(ts if ts is not None else time.time()), float(value)),
        )

    # ── Evaluate ─────────────────────────────────────────

    def evaluate(
        self,
        kpi: str,
        *,
        threshold: float,
        direction: Direction,
        now: float | None = None,
    ) -> PreBreachAlert:
        if direction not in ("above", "below"):
            raise ValueError("direction must be above|below")
        series = self._series.get(kpi)
        now = float(now if now is not None else time.time())
        points = list(series.window) if series is not None else []
        n = len(points)
        if n < self._min_samples:
            return PreBreachAlert(
                kpi=kpi,
                current_value=points[-1][1] if points else 0.0,
                threshold=float(threshold),
                direction=direction,
                projected_breach_s=None,
                confidence=0.0,
                severity="none",
                slope=0.0,
                n_samples=n,
                note=(
                    f"need ≥ {self._min_samples} samples; "
                    f"have {n}"
                ),
            )
        slope, intercept, r2 = _linear_fit(points)
        current_value = points[-1][1]
        # Already breaching?
        breached_now = (
            (direction == "above" and current_value > threshold)
            or (direction == "below" and current_value < threshold)
        )
        if breached_now:
            return PreBreachAlert(
                kpi=kpi,
                current_value=current_value,
                threshold=float(threshold),
                direction=direction,
                projected_breach_s=0.0,
                confidence=max(r2, 0.5),
                severity="critical",
                slope=slope,
                n_samples=n,
                note="already breaching",
            )
        # Solve slope*t + intercept = threshold for t
        if slope == 0:
            return PreBreachAlert(
                kpi=kpi,
                current_value=current_value,
                threshold=float(threshold),
                direction=direction,
                projected_breach_s=None,
                confidence=r2,
                severity="none",
                slope=0.0,
                n_samples=n,
                note="zero slope — no trajectory",
            )
        breach_ts = (threshold - intercept) / slope
        # Sign check: ensure trajectory actually heads toward threshold
        heading_right_way = (
            (direction == "above" and slope > 0)
            or (direction == "below" and slope < 0)
        )
        if not heading_right_way:
            return PreBreachAlert(
                kpi=kpi,
                current_value=current_value,
                threshold=float(threshold),
                direction=direction,
                projected_breach_s=None,
                confidence=r2,
                severity="none",
                slope=slope,
                n_samples=n,
                note=(
                    f"trajectory heading away from threshold "
                    f"({direction})"
                ),
            )
        seconds_to_breach = breach_ts - now
        if seconds_to_breach < 0:
            # Projection is in the past → expect breach already
            return PreBreachAlert(
                kpi=kpi,
                current_value=current_value,
                threshold=float(threshold),
                direction=direction,
                projected_breach_s=0.0,
                confidence=r2,
                severity="critical",
                slope=slope,
                n_samples=n,
                note="projection suggests breach overdue",
            )
        severity: Severity
        if seconds_to_breach <= self._critical_horizon:
            severity = "critical"
        elif seconds_to_breach <= self._warning_horizon:
            severity = "warning"
        else:
            severity = "info"
        return PreBreachAlert(
            kpi=kpi,
            current_value=current_value,
            threshold=float(threshold),
            direction=direction,
            projected_breach_s=seconds_to_breach,
            confidence=r2,
            severity=severity,
            slope=slope,
            n_samples=n,
        )

    # ── Query ────────────────────────────────────────────

    def summary(self, kpi: str) -> dict[str, Any] | None:
        series = self._series.get(kpi)
        if series is None or not series.window:
            return None
        values = [v for _, v in series.window]
        return {
            "kpi": kpi,
            "samples": len(values),
            "latest": round(values[-1], 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    def reset(self, kpi: str | None = None) -> int:
        if kpi is None:
            n = len(self._series)
            self._series.clear()
            return n
        return 1 if self._series.pop(kpi, None) is not None else 0

    def stats(self) -> dict[str, Any]:
        return {
            "tracked_kpis": len(self._series),
            "window": self._window,
            "min_samples": self._min_samples,
        }
