"""Temporal reasoning — time-aware queries over memory.

Everything built so far treats memory as a set. Time is used only
for ordering. Real operators care about *when* things happen:

  • "is today's ROAS normal for a Tuesday?"
  • "do our launches typically peak at day 5?"
  • "is November seasonally hot for this niche?"
  • "has this launch stayed under 3-day median too long?"

This module layers temporal statistics on the memory timeline:

  day_of_week(cat, action)  — mean value per weekday (0 = Monday)
  hour_of_day(cat, action)   — mean value per hour
  convergence_days(niche)    — median days to first scale/kill verdict
  seasonality(cat, window_days=60)  — simple autocorrelation at
                                       weekly lags
  answer(question)          — cheap dispatcher for the common queries

All derivations are pure SQL + numpy-free math over memory. Intended
as background signals for the reasoner, oracle, and digest narrator.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")
_SECONDS_PER_DAY = 86_400


@dataclass
class WeekdayProfile:
    category: str
    action: str | None
    per_day: dict[int, float]            # 0=Monday … 6=Sunday
    sample_counts: dict[int, int]
    best_day: int
    worst_day: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "action": self.action,
            "per_day": {k: round(v, 3) for k, v in self.per_day.items()},
            "sample_counts": self.sample_counts,
            "best_day": self.best_day,
            "worst_day": self.worst_day,
        }


@dataclass
class HourProfile:
    category: str
    per_hour: dict[int, float]
    sample_counts: dict[int, int]
    peak_hour: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "per_hour": {k: round(v, 3) for k, v in self.per_hour.items()},
            "sample_counts": self.sample_counts,
            "peak_hour": self.peak_hour,
        }


@dataclass
class ConvergenceStats:
    niche: str
    samples: int
    median_days: float
    p25_days: float
    p75_days: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "niche": self.niche,
            "samples": self.samples,
            "median_days": round(self.median_days, 2),
            "p25_days": round(self.p25_days, 2),
            "p75_days": round(self.p75_days, 2),
        }


@dataclass
class Seasonality:
    category: str
    window_days: int
    weekly_autocorr: float
    monthly_autocorr: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "window_days": self.window_days,
            "weekly_autocorr": round(self.weekly_autocorr, 3),
            "monthly_autocorr": round(self.monthly_autocorr, 3),
        }


# ── Public API ──────────────────────────────────────────────

def day_of_week(category: str, action: str | None = None) -> WeekdayProfile:
    rows = _pull_events(category, action, limit=5000)
    per_day: dict[int, list[float]] = {i: [] for i in range(7)}
    for ts, score in rows:
        dow = datetime.fromtimestamp(ts, tz=timezone.utc).weekday()
        per_day[dow].append(score)
    means = {k: (sum(v) / len(v) if v else 0.0) for k, v in per_day.items()}
    counts = {k: len(v) for k, v in per_day.items()}
    sampled = {k: means[k] for k in means if counts[k] > 0}
    if sampled:
        best = max(sampled, key=lambda d: sampled[d])
        worst = min(sampled, key=lambda d: sampled[d])
    else:
        best = 0
        worst = 0
    return WeekdayProfile(
        category=category, action=action,
        per_day=means, sample_counts=counts,
        best_day=best, worst_day=worst,
    )


def hour_of_day(category: str) -> HourProfile:
    rows = _pull_events(category, None, limit=5000)
    per_hour: dict[int, list[float]] = {i: [] for i in range(24)}
    for ts, score in rows:
        hr = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        per_hour[hr].append(score)
    means = {k: (sum(v) / len(v) if v else 0.0) for k, v in per_hour.items()}
    counts = {k: len(v) for k, v in per_hour.items()}
    peak = max(means, key=lambda h: means[h])
    return HourProfile(
        category=category, per_hour=means,
        sample_counts=counts, peak_hour=peak,
    )


def convergence_days(niche: str) -> ConvergenceStats:
    """Median days between launch-registration and first verdict for
    launches matching *niche*."""
    if not niche:
        return ConvergenceStats(niche="", samples=0, median_days=0,
                                 p25_days=0, p75_days=0)
    deltas = _launch_to_verdict_deltas(niche=niche.lower())
    if not deltas:
        return ConvergenceStats(niche=niche, samples=0, median_days=0,
                                 p25_days=0, p75_days=0)
    deltas.sort()
    n = len(deltas)
    def pct(p: float) -> float:
        idx = int(min(n - 1, max(0, p * n)))
        return deltas[idx]
    return ConvergenceStats(
        niche=niche, samples=n,
        median_days=pct(0.5),
        p25_days=pct(0.25),
        p75_days=pct(0.75),
    )


def seasonality(category: str, window_days: int = 60) -> Seasonality:
    """Weekly + monthly autocorrelation over recent daily event counts.
    Value in [-1, 1]; >0.3 = meaningful seasonal signal."""
    rows = _pull_events(category, None, limit=10_000,
                        since_ts=time.time() - window_days * _SECONDS_PER_DAY)
    if not rows:
        return Seasonality(category=category, window_days=window_days,
                           weekly_autocorr=0.0, monthly_autocorr=0.0)

    # Bucket into daily counts
    by_day: dict[int, int] = {}
    now = time.time()
    for ts, _ in rows:
        day_index = int((now - ts) / _SECONDS_PER_DAY)
        by_day[day_index] = by_day.get(day_index, 0) + 1
    counts = [by_day.get(i, 0) for i in range(window_days)]
    return Seasonality(
        category=category, window_days=window_days,
        weekly_autocorr=_autocorr(counts, lag=7),
        monthly_autocorr=_autocorr(counts, lag=30),
    )


def answer(question: str) -> dict[str, Any]:
    """Cheap dispatcher for the common temporal questions."""
    q = (question or "").lower()
    if "day of week" in q or "weekday" in q:
        return day_of_week("order").as_dict()
    if "peak hour" in q or "best hour" in q:
        return hour_of_day("order").as_dict()
    if "convergence" in q or "how long" in q or "days to" in q:
        return convergence_days(_niche_from(q) or "").as_dict()
    if "season" in q:
        return seasonality("order").as_dict()
    return {"error": f"unrecognised temporal question: {question!r}"}


# ── Internals ───────────────────────────────────────────────

def _pull_events(
    category: str, action: str | None,
    limit: int, since_ts: float | None = None,
) -> list[tuple[float, float]]:
    if not _DB_PATH.exists() or not category:
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        sql = (
            "SELECT timestamp, score FROM memories "
            "WHERE category=? "
        )
        params: list[Any] = [category]
        if action:
            sql += "AND action=? "
            params.append(action)
        if since_ts is not None:
            sql += "AND timestamp >= ? "
            params.append(since_ts)
        sql += "ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))
        cur.execute(sql, params)
        return [(float(ts or 0), float(s or 0)) for ts, s in cur.fetchall()]
    finally:
        conn.close()


def _launch_to_verdict_deltas(niche: str) -> list[float]:
    """For each matching launch, compute days between registration
    and the evaluator's current verdict (if any)."""
    deltas: list[float] = []
    try:
        from core.autonomous.launch_evaluator import evaluate
        from core.autonomous.self_critic import _niche_map
        report = evaluate()
        niches = _niche_map(limit=500)
    except Exception:
        return deltas

    target = niche.strip().lower()
    for s in (report.kill_recommendations
              + report.scale_recommendations
              + report.monitor_recommendations):
        if target and niches.get(s.launch_id, "").lower() != target:
            continue
        if s.days_live <= 0:
            continue
        if s.verdict in ("kill", "scale"):
            deltas.append(float(s.days_live))
    return deltas


def _autocorr(series: list[int], lag: int) -> float:
    n = len(series)
    if n <= lag:
        return 0.0
    mean = sum(series) / n
    num = sum(
        (series[i] - mean) * (series[i + lag] - mean)
        for i in range(n - lag)
    )
    den = sum((x - mean) ** 2 for x in series)
    if den <= 0:
        return 0.0
    return num / den


def _niche_from(q: str) -> str | None:
    tokens = q.replace("?", " ").split()
    for t in tokens:
        if t.endswith("niche"):
            return t.replace("niche", "").strip(" _-")
    return None
