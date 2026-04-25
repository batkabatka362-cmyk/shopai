"""Time-series trend detector.

Static ROAS / revenue / order-count numbers are only half the story.
A launch that moved from ROAS 2.2 → 1.4 over three days is a
time-series problem — the verdict should *kill faster* than a
launch that's been steadily at 1.4 all along.

This module scans the recent memory timeline (``category=order``
plus ``category=launch`` events) and produces a time-ordered signal
bundle per launch (and globally). For each series we compute:

  • slope  — least-squares over the last N samples, normalised by
             series magnitude (∆ per day in units of the mean)
  • z_last — the most recent sample as a z-score vs the rolling
             window mean/stddev (N = 7)
  • trend  — "up", "flat", "down" using |slope| > 0.15 and z_last

Detected inflections (slope sign flip or z_last crossing ±2) are
persisted as ``category=trend score=3.5`` memory events and
surfaced on ``cycle_result.phases.trend_detector`` so the
autonomous loop can act.

All math is pure Python (O(N) per series). No LLM, no external
network — runs in a few ms per cycle even against 500 rows.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")
_MIN_SAMPLES = 3
_WINDOW = 7
_FLAT_SLOPE = 0.15
_ZFLAG = 2.0


@dataclass
class SeriesTrend:
    key: str                    # e.g. "launch:abc/roas" or "global/orders"
    samples: int
    mean: float
    stddev: float
    slope: float
    z_last: float
    trend: str                   # "up" | "flat" | "down"
    inflection: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "samples": self.samples,
            "mean": round(self.mean, 3),
            "stddev": round(self.stddev, 3),
            "slope": round(self.slope, 4),
            "z_last": round(self.z_last, 3),
            "trend": self.trend,
            "inflection": self.inflection,
        }


@dataclass
class TrendReport:
    series: list[SeriesTrend] = field(default_factory=list)
    inflections: list[SeriesTrend] = field(default_factory=list)
    recorded: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_count": len(self.series),
            "inflection_count": len(self.inflections),
            "recorded": self.recorded,
            "inflections": [s.as_dict() for s in self.inflections],
        }


def detect() -> TrendReport:
    """Scan recent memory, compute per-series trends, record
    inflections as memory events. Never raises."""
    try:
        series_by_key = _collect_series()
    except Exception:
        return TrendReport()

    report = TrendReport()
    for key, samples in series_by_key.items():
        if len(samples) < _MIN_SAMPLES:
            continue
        trend = _compute(key, samples)
        report.series.append(trend)
        if trend.inflection:
            report.inflections.append(trend)
            if _persist(trend):
                report.recorded += 1
    return report


def _collect_series(limit: int = 1000) -> dict[str, list[tuple[float, float]]]:
    """Return {series_key: [(timestamp, value)]} sorted oldest-first."""
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if not _DB_PATH.exists():
        return out
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT category, content, tags, timestamp "
            "FROM memories "
            "WHERE category IN ('order', 'launch', 'competitor') "
            "  AND timestamp > ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (time.time() - 30 * 86400, int(limit)),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    for category, content_json, tags_json, ts in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            c = {}
        try:
            tags = json.loads(tags_json or "[]")
        except (json.JSONDecodeError, ValueError):
            tags = []

        if category == "order":
            total = float(c.get("total_price", 0) or c.get("total", 0) or 0)
            out["global/revenue"].append((ts, total))
            out["global/orders"].append((ts, 1.0))
            for t in tags:
                if isinstance(t, str) and t.startswith("launch:"):
                    lid = t.split(":", 1)[1]
                    out[f"launch:{lid}/revenue"].append((ts, total))
        elif category == "launch":
            lid = c.get("launch_id") or ""
            if lid:
                out[f"launch:{lid}/registered"].append((ts, 1.0))
        elif category == "competitor":
            new_p = c.get("new_price")
            if isinstance(new_p, (int, float)):
                key = c.get("url") or "competitor:unknown"
                out[f"competitor/{key[-40:]}/price"].append((ts, float(new_p)))

    for k, pts in out.items():
        pts.sort(key=lambda x: x[0])
    return out


def _compute(key: str, samples: list[tuple[float, float]]) -> SeriesTrend:
    values = [v for _, v in samples]
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    stddev = math.sqrt(var) if var > 0 else 0.0

    # Simple linear regression over the last _WINDOW samples (or all)
    window = samples[-_WINDOW:]
    if len(window) >= 2:
        # Normalise time to unit steps so slope is per-sample
        xs = list(range(len(window)))
        ys = [v for _, v in window]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs) or 1.0
        raw_slope = num / den
        slope = raw_slope / (abs(my) + 1e-6)   # normalise by magnitude
    else:
        slope = 0.0

    last = values[-1]
    z_last = (last - mean) / stddev if stddev > 0 else 0.0

    if abs(slope) < _FLAT_SLOPE:
        direction = "flat"
    elif slope > 0:
        direction = "up"
    else:
        direction = "down"

    inflection = abs(z_last) >= _ZFLAG or (
        len(window) >= 4
        and _sign_flip(window)
    )

    return SeriesTrend(
        key=key, samples=n, mean=mean, stddev=stddev,
        slope=slope, z_last=z_last, trend=direction,
        inflection=inflection,
    )


def _sign_flip(window: list[tuple[float, float]]) -> bool:
    """Return True if the second half's slope has opposite sign from
    the first half — a classic inflection point."""
    half = len(window) // 2
    if half < 2:
        return False
    first = [v for _, v in window[:half]]
    second = [v for _, v in window[half:]]

    def slope(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        xs = list(range(len(values)))
        mx = sum(xs) / len(xs)
        my = sum(values) / len(values)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
        den = sum((x - mx) ** 2 for x in xs) or 1.0
        return num / den

    s1 = slope(first)
    s2 = slope(second)
    return s1 * s2 < -1e-6  # opposite signs (strict)


def _persist(trend: SeriesTrend) -> bool:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="trend",
            content=trend.as_dict(),
            action=trend.trend,
            score=3.5,
            tags=["trend", trend.trend, trend.key],
        )
        return True
    except Exception:
        return False
