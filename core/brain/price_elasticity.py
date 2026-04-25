"""Price elasticity — learn demand curves per product/segment.

uplift_estimator answers "did treatment X help?". price_elasticity
answers a sharper question that drives revenue: *"if I set the price
to $P, how many units will sell, and what's the expected revenue?"*

We fit a constant-elasticity log-log model from observed
(price, units) pairs:

    log(units) ≈ a + ε · log(price)

where ε is the elasticity (typically negative — higher price ⇒ fewer
units). Pure-stdlib least-squares closed form, deterministic.

Per-segment models so audio.headphones doesn't pollute fashion.tshirt.
SQLite-persisted. Falls back to "insufficient" verdict when fewer
than ``min_samples`` observations are present for a segment.

API:

    pe.observe("audio.headphones", price=29.99, units=120)
    fit = pe.fit("audio.headphones")
    rev = pe.predict("audio.headphones", price=34.99)
    # → {"units": 95.0, "revenue": 3324.05, "elasticity": -1.6}

    optimum = pe.optimal_revenue_price(
        "audio.headphones",
        candidates=[19.99, 24.99, 29.99, 34.99, 39.99],
    )
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.price_elasticity")


@dataclass
class Sample:
    price: float
    units: float
    ts: float


@dataclass
class Fit:
    segment: str
    elasticity: float
    intercept: float          # log-units intercept (log a)
    n: int
    r_squared: float
    status: str               # "ok" | "insufficient" | "degenerate"

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "elasticity": round(self.elasticity, 4),
            "intercept": round(self.intercept, 4),
            "n": self.n,
            "r_squared": round(self.r_squared, 4),
            "status": self.status,
        }


@dataclass
class Prediction:
    segment: str
    price: float
    units: float
    revenue: float
    elasticity: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "price": round(self.price, 4),
            "units": round(self.units, 4),
            "revenue": round(self.revenue, 4),
            "elasticity": round(self.elasticity, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_obs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    segment   TEXT NOT NULL,
    price     REAL NOT NULL,
    units     REAL NOT NULL,
    ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_obs_seg ON price_obs(segment);
"""


class PriceElasticity:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        min_samples: int = 5,
    ) -> None:
        if min_samples < 2:
            raise ValueError("min_samples must be ≥ 2")
        self._lock = threading.Lock()
        self._min_samples = int(min_samples)
        self._samples: dict[str, list[Sample]] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT segment, price, units, ts FROM price_obs",
            ):
                self._samples.setdefault(row[0], []).append(
                    Sample(
                        price=float(row[1]),
                        units=float(row[2]),
                        ts=float(row[3]),
                    ),
                )

    # ── Intake ────────────────────────────────────────────

    def observe(
        self,
        segment: str,
        *,
        price: float,
        units: float,
        ts: float | None = None,
    ) -> None:
        if not segment:
            raise ValueError("segment required")
        if price <= 0 or units < 0:
            raise ValueError("price > 0 and units ≥ 0 required")
        sample = Sample(
            price=float(price),
            units=float(units),
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            self._samples.setdefault(segment, []).append(sample)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO price_obs(segment, price, units, ts) "
                    "VALUES (?, ?, ?, ?)",
                    (segment, sample.price, sample.units, sample.ts),
                )
                self._conn.commit()

    # ── Fit ──────────────────────────────────────────────

    def fit(self, segment: str) -> Fit:
        with self._lock:
            samples = list(self._samples.get(segment, []))
        if len(samples) < self._min_samples:
            return Fit(
                segment=segment, elasticity=0.0, intercept=0.0,
                n=len(samples), r_squared=0.0,
                status="insufficient",
            )
        # Drop zero-units rows so log is defined; if no rows survive,
        # mark as degenerate so the caller doesn't pretend to predict.
        usable = [s for s in samples if s.units > 0 and s.price > 0]
        if len(usable) < self._min_samples:
            return Fit(
                segment=segment, elasticity=0.0, intercept=0.0,
                n=len(usable), r_squared=0.0,
                status="degenerate",
            )
        xs = [math.log(s.price) for s in usable]
        ys = [math.log(s.units) for s in usable]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return Fit(
                segment=segment, elasticity=0.0,
                intercept=my, n=n, r_squared=0.0,
                status="degenerate",
            )
        slope = num / den       # elasticity
        intercept = my - slope * mx
        ss_tot = sum((y - my) ** 2 for y in ys)
        if ss_tot == 0:
            r2 = 1.0
        else:
            ss_res = sum(
                (y - (slope * x + intercept)) ** 2
                for x, y in zip(xs, ys)
            )
            r2 = max(0.0, 1.0 - ss_res / ss_tot)
        return Fit(
            segment=segment,
            elasticity=slope,
            intercept=intercept,
            n=n, r_squared=r2,
            status="ok",
        )

    # ── Predict ──────────────────────────────────────────

    def predict(
        self,
        segment: str,
        *,
        price: float,
    ) -> Prediction | None:
        if price <= 0:
            return None
        fit = self.fit(segment)
        if fit.status != "ok":
            return None
        log_units = fit.intercept + fit.elasticity * math.log(price)
        units = max(0.0, math.exp(log_units))
        return Prediction(
            segment=segment,
            price=float(price),
            units=units,
            revenue=units * float(price),
            elasticity=fit.elasticity,
        )

    def optimal_revenue_price(
        self,
        segment: str,
        candidates: Iterable[float],
    ) -> Prediction | None:
        best: Prediction | None = None
        for p in candidates:
            pred = self.predict(segment, price=float(p))
            if pred is None:
                continue
            if best is None or pred.revenue > best.revenue:
                best = pred
        return best

    # ── Stats / maintenance ──────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "segments": len(self._samples),
                "samples": sum(
                    len(v) for v in self._samples.values()
                ),
                "by_segment": {
                    s: len(v) for s, v in self._samples.items()
                },
            }

    def reset(self, segment: str | None = None) -> int:
        with self._lock:
            if segment is None:
                n = sum(len(v) for v in self._samples.values())
                self._samples.clear()
                if self._conn is not None:
                    self._conn.execute("DELETE FROM price_obs")
                    self._conn.commit()
                return n
            n = len(self._samples.pop(segment, []))
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM price_obs WHERE segment=?",
                    (segment,),
                )
                self._conn.commit()
            return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
