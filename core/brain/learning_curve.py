"""Learning curve — does the brain actually get better over time?

Every subsystem claims it learns. trust_calibrator, fraud_detector,
pattern_discovery… they all update parameters every cycle. But are
they actually improving? Or just drifting? ``learning_curve`` answers
that question empirically.

Record a metric each time a subsystem runs:

    tracker.record("trust_calibrator", "auc", 0.72, cycle=104)
    tracker.record("fraud_detector",   "f1",  0.55, cycle=104)

Then query the curve:

    curve = tracker.curve("trust_calibrator", "auc", window=50)
    # → slope, intercept, trend ("improving"/"plateau"/"regressing"),
    #   r_squared, latest, delta_vs_start

Or rank subsystems by improvement rate to spotlight winners & losers:

    leaders = tracker.rank(metric="f1", window=100, top_n=5)

Pure stdlib. SQLite-persisted. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Trend = Literal["improving", "plateau", "regressing", "insufficient"]


@dataclass
class Point:
    subsystem: str
    metric: str
    value: float
    cycle: int
    ts: float


@dataclass
class Curve:
    subsystem: str
    metric: str
    n: int
    slope: float          # value change per cycle
    intercept: float
    r_squared: float      # 0..1 fit strength
    trend: Trend
    latest: float
    start: float
    delta: float          # latest − first-in-window
    window: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "metric": self.metric,
            "n": self.n,
            "slope": round(self.slope, 6),
            "intercept": round(self.intercept, 6),
            "r_squared": round(self.r_squared, 4),
            "trend": self.trend,
            "latest": round(self.latest, 4),
            "start": round(self.start, 4),
            "delta": round(self.delta, 4),
            "window": self.window,
        }


def _classify(slope: float, r_squared: float, scale: float) -> Trend:
    # scale = typical value magnitude; use it to decide "meaningful"
    # slope. If the metric ranges 0..1, a slope of 1e-5 per cycle is
    # noise; 1e-3 is a real trend.
    min_meaningful = max(scale, 1.0) * 1e-4
    if r_squared < 0.1:
        return "plateau"
    if slope > min_meaningful:
        return "improving"
    if slope < -min_meaningful:
        return "regressing"
    return "plateau"


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
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
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0:
        return slope, intercept, 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r2


class LearningCurveTracker:
    """SQLite-backed ledger of subsystem metrics over time."""

    def __init__(self, db_path: str | Path = "data/learning_curve.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS points (
                    subsystem TEXT NOT NULL,
                    metric    TEXT NOT NULL,
                    value     REAL NOT NULL,
                    cycle     INTEGER NOT NULL,
                    ts        REAL NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sm_cycle "
                "ON points(subsystem, metric, cycle)"
            )
            self._conn.commit()

    def record(
        self,
        subsystem: str,
        metric: str,
        value: float,
        cycle: int | None = None,
        ts: float | None = None,
    ) -> None:
        if not subsystem or not metric:
            raise ValueError("subsystem and metric required")
        with self._lock:
            if cycle is None:
                row = self._conn.execute(
                    "SELECT COALESCE(MAX(cycle), 0) + 1 FROM points "
                    "WHERE subsystem=? AND metric=?",
                    (subsystem, metric),
                ).fetchone()
                cycle = int(row[0])
            self._conn.execute(
                "INSERT INTO points(subsystem, metric, value, cycle, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (subsystem, metric, float(value), int(cycle),
                 float(ts if ts is not None else time.time())),
            )
            self._conn.commit()

    def points(
        self,
        subsystem: str,
        metric: str,
        window: int = 100,
    ) -> list[Point]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT subsystem, metric, value, cycle, ts FROM points "
                "WHERE subsystem=? AND metric=? "
                "ORDER BY cycle DESC LIMIT ?",
                (subsystem, metric, int(window)),
            ).fetchall()
        rows.reverse()
        return [Point(*r) for r in rows]

    def curve(
        self,
        subsystem: str,
        metric: str,
        window: int = 100,
    ) -> Curve:
        pts = self.points(subsystem, metric, window=window)
        n = len(pts)
        if n < 2:
            latest = pts[-1].value if pts else 0.0
            return Curve(
                subsystem=subsystem, metric=metric, n=n,
                slope=0.0, intercept=latest, r_squared=0.0,
                trend="insufficient", latest=latest, start=latest,
                delta=0.0, window=window,
            )
        xs = [float(p.cycle) for p in pts]
        ys = [float(p.value) for p in pts]
        slope, intercept, r2 = _linear_fit(xs, ys)
        scale = max(abs(ys[0]), abs(ys[-1]), 1e-9)
        return Curve(
            subsystem=subsystem, metric=metric, n=n,
            slope=slope, intercept=intercept, r_squared=r2,
            trend=_classify(slope, r2, scale),
            latest=ys[-1], start=ys[0],
            delta=ys[-1] - ys[0], window=window,
        )

    def rank(
        self,
        metric: str,
        window: int = 100,
        top_n: int = 10,
    ) -> list[Curve]:
        """Rank all subsystems tracking ``metric`` by slope (fastest
        improvers first). Regressors appear last."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT subsystem FROM points WHERE metric=?",
                (metric,),
            ).fetchall()
        curves = [self.curve(r[0], metric, window=window) for r in rows]
        curves.sort(key=lambda c: -c.slope)
        return curves[:top_n]

    def forecast(
        self,
        subsystem: str,
        metric: str,
        steps: int = 10,
        window: int = 100,
    ) -> list[float]:
        """Project ``steps`` cycles ahead using linear fit."""
        c = self.curve(subsystem, metric, window=window)
        if c.trend == "insufficient":
            return [c.latest] * steps
        pts = self.points(subsystem, metric, window=window)
        last_cycle = pts[-1].cycle
        return [
            c.slope * (last_cycle + i) + c.intercept
            for i in range(1, steps + 1)
        ]

    def clear(self, subsystem: str | None = None) -> int:
        with self._lock:
            if subsystem is None:
                n = self._conn.execute(
                    "SELECT COUNT(*) FROM points"
                ).fetchone()[0]
                self._conn.execute("DELETE FROM points")
            else:
                n = self._conn.execute(
                    "SELECT COUNT(*) FROM points WHERE subsystem=?",
                    (subsystem,),
                ).fetchone()[0]
                self._conn.execute(
                    "DELETE FROM points WHERE subsystem=?",
                    (subsystem,),
                )
            self._conn.commit()
        return int(n)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
