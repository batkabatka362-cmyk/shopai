"""Customer LTV — predict lifetime value from observable signals.

Acquisition spend should be capped by *expected* customer lifetime
value, not by today's order. customer_ltv learns a lightweight LTV
predictor from a stream of order observations:

    observe(customer_id, ts, order_value, refund_value=0)

It maintains per-customer aggregates and computes:

  • frequency  — orders per active week
  • monetary   — average order value (net of refunds)
  • recency    — days since last order
  • cohort_age — days since first order

The predicted LTV uses a deterministic exponential-decay survival
model:

    LTV = AOV × frequency × Σ_{t=1..H} survival(t)
    survival(t) = (1 − churn_hazard)**t

where churn_hazard is computed empirically from the cohort's
observed survival curve. No ML library — pure stdlib closed-form.

Bonus: ``segment_summary()`` aggregates over a configurable cohort
key (e.g. acquisition_source, niche) so callers can drive
segment-level retention decisions.

SQLite-persisted, deterministic, fail-soft.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.customer_ltv")


@dataclass
class _OrderRow:
    customer_id: str
    ts: float
    order_value: float
    refund_value: float
    cohort_keys: dict[str, str]


@dataclass
class CustomerProfile:
    customer_id: str
    n_orders: int
    total_spend: float
    refunded: float
    first_ts: float
    last_ts: float
    cohort_keys: dict[str, str]

    @property
    def aov(self) -> float:
        if self.n_orders == 0:
            return 0.0
        return max(0.0, (self.total_spend - self.refunded) / self.n_orders)

    @property
    def cohort_age_days(self) -> float:
        if self.first_ts == 0:
            return 0.0
        return max(0.0, (time.time() - self.first_ts) / 86_400.0)

    @property
    def recency_days(self) -> float:
        if self.last_ts == 0:
            return 0.0
        return max(0.0, (time.time() - self.last_ts) / 86_400.0)

    @property
    def frequency_per_week(self) -> float:
        weeks = max(1.0, self.cohort_age_days / 7.0)
        return self.n_orders / weeks

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "n_orders": self.n_orders,
            "total_spend": round(self.total_spend, 4),
            "refunded": round(self.refunded, 4),
            "aov": round(self.aov, 4),
            "cohort_age_days": round(self.cohort_age_days, 2),
            "recency_days": round(self.recency_days, 2),
            "frequency_per_week": round(self.frequency_per_week, 4),
            "cohort_keys": dict(self.cohort_keys),
        }


@dataclass
class LtvEstimate:
    customer_id: str
    horizon_weeks: int
    expected_value: float
    churn_hazard_weekly: float
    aov: float
    frequency_per_week: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "horizon_weeks": self.horizon_weeks,
            "expected_value": round(self.expected_value, 4),
            "churn_hazard_weekly": round(self.churn_hazard_weekly, 4),
            "aov": round(self.aov, 4),
            "frequency_per_week": round(self.frequency_per_week, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ltv_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  TEXT NOT NULL,
    ts           REAL NOT NULL,
    order_value  REAL NOT NULL,
    refund_value REAL NOT NULL DEFAULT 0,
    cohort_keys  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ltv_cust ON ltv_orders(customer_id);
"""


class CustomerLTV:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        churn_silent_weeks: float = 8.0,
    ) -> None:
        if churn_silent_weeks <= 0:
            raise ValueError("churn_silent_weeks must be positive")
        # RLock — stats()/segment_summary() call _churn_hazard()
        # which also acquires the lock; non-reentrant Lock would
        # deadlock the second acquire.
        self._lock = threading.RLock()
        self._churn_silent_weeks = float(churn_silent_weeks)
        self._orders: list[_OrderRow] = []
        self._profiles: dict[str, CustomerProfile] = {}
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
        import json
        with self._lock:
            for row in self._conn.execute(
                "SELECT customer_id, ts, order_value, refund_value, "
                "cohort_keys FROM ltv_orders ORDER BY ts ASC",
            ):
                try:
                    keys = json.loads(row[4] or "{}")
                except (json.JSONDecodeError, ValueError):
                    keys = {}
                self._apply(_OrderRow(
                    customer_id=row[0], ts=float(row[1]),
                    order_value=float(row[2]),
                    refund_value=float(row[3]),
                    cohort_keys={
                        str(k): str(v) for k, v in keys.items()
                    },
                ))

    # ── Intake ────────────────────────────────────────────

    def observe(
        self,
        customer_id: str,
        *,
        order_value: float,
        refund_value: float = 0.0,
        ts: float | None = None,
        cohort_keys: dict[str, str] | None = None,
    ) -> CustomerProfile:
        if not customer_id:
            raise ValueError("customer_id required")
        if order_value < 0 or refund_value < 0:
            raise ValueError("order_value, refund_value must be ≥ 0")
        row = _OrderRow(
            customer_id=customer_id,
            ts=float(ts if ts is not None else time.time()),
            order_value=float(order_value),
            refund_value=float(refund_value),
            cohort_keys={
                str(k): str(v)
                for k, v in (cohort_keys or {}).items()
            },
        )
        with self._lock:
            self._orders.append(row)
            self._apply(row)
            if self._conn is not None:
                import json
                self._conn.execute(
                    "INSERT INTO ltv_orders"
                    "(customer_id, ts, order_value, refund_value, "
                    " cohort_keys) VALUES (?, ?, ?, ?, ?)",
                    (
                        row.customer_id, row.ts,
                        row.order_value, row.refund_value,
                        json.dumps(row.cohort_keys, sort_keys=True),
                    ),
                )
                self._conn.commit()
        return self._profiles[customer_id]

    def _apply(self, row: _OrderRow) -> None:
        prof = self._profiles.get(row.customer_id)
        if prof is None:
            prof = CustomerProfile(
                customer_id=row.customer_id,
                n_orders=0, total_spend=0.0, refunded=0.0,
                first_ts=row.ts, last_ts=row.ts,
                cohort_keys=dict(row.cohort_keys),
            )
            self._profiles[row.customer_id] = prof
        prof.n_orders += 1
        prof.total_spend += row.order_value
        prof.refunded += row.refund_value
        if row.ts > prof.last_ts:
            prof.last_ts = row.ts
        if row.ts < prof.first_ts:
            prof.first_ts = row.ts
        # Cohort keys merge: later orders win (assume more accurate)
        for k, v in row.cohort_keys.items():
            prof.cohort_keys[k] = v

    # ── Churn hazard ─────────────────────────────────────

    def _churn_hazard(self) -> float:
        """Population-level weekly churn hazard.

        churned ≡ recency > churn_silent_weeks. We treat hazard as the
        fraction of customers in that bucket out of all observed —
        clipped to [0.01, 0.5] so predictions stay finite."""
        with self._lock:
            profiles = list(self._profiles.values())
        if not profiles:
            return 0.1
        churned = sum(
            1 for p in profiles
            if p.recency_days / 7.0 > self._churn_silent_weeks
        )
        raw = churned / len(profiles)
        return max(0.01, min(0.5, raw))

    # ── Predict ──────────────────────────────────────────

    def predict(
        self,
        customer_id: str,
        *,
        horizon_weeks: int = 52,
    ) -> LtvEstimate | None:
        if horizon_weeks < 1:
            raise ValueError("horizon_weeks must be ≥ 1")
        with self._lock:
            prof = self._profiles.get(customer_id)
        if prof is None or prof.n_orders == 0:
            return None
        hazard = self._churn_hazard()
        survival_total = 0.0
        prob = 1.0
        for _ in range(horizon_weeks):
            prob *= (1.0 - hazard)
            survival_total += prob
        expected = prof.aov * prof.frequency_per_week * survival_total
        return LtvEstimate(
            customer_id=customer_id,
            horizon_weeks=horizon_weeks,
            expected_value=expected,
            churn_hazard_weekly=hazard,
            aov=prof.aov,
            frequency_per_week=prof.frequency_per_week,
        )

    # ── Cohort segment summary ───────────────────────────

    def segment_summary(
        self,
        cohort_key: str,
        *,
        horizon_weeks: int = 52,
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[CustomerProfile]] = defaultdict(list)
        with self._lock:
            for p in self._profiles.values():
                groups[p.cohort_keys.get(cohort_key, "(unknown)")].append(p)
        if not groups:
            return []
        hazard = self._churn_hazard()
        survival_total = 0.0
        prob = 1.0
        for _ in range(horizon_weeks):
            prob *= (1.0 - hazard)
            survival_total += prob
        out: list[dict[str, Any]] = []
        for value, members in groups.items():
            n = len(members)
            mean_aov = (
                sum(m.aov for m in members) / n if n else 0.0
            )
            mean_freq = (
                sum(m.frequency_per_week for m in members) / n
                if n else 0.0
            )
            ltv = mean_aov * mean_freq * survival_total
            out.append({
                "cohort_value": value,
                "n_customers": n,
                "mean_aov": round(mean_aov, 4),
                "mean_frequency_per_week": round(mean_freq, 4),
                "expected_ltv": round(ltv, 4),
            })
        out.sort(key=lambda d: -d["expected_ltv"])
        return out

    # ── Stats / maintenance ──────────────────────────────

    def profile(self, customer_id: str) -> CustomerProfile | None:
        return self._profiles.get(customer_id)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "customers": len(self._profiles),
                "orders": len(self._orders),
                "churn_hazard_weekly": round(self._churn_hazard(), 4),
            }

    def reset(self, customer_id: str | None = None) -> int:
        with self._lock:
            if customer_id is None:
                n = len(self._orders)
                self._orders.clear()
                self._profiles.clear()
                if self._conn is not None:
                    self._conn.execute("DELETE FROM ltv_orders")
                    self._conn.commit()
                return n
            n = sum(
                1 for o in self._orders if o.customer_id == customer_id
            )
            self._orders = [
                o for o in self._orders if o.customer_id != customer_id
            ]
            self._profiles.pop(customer_id, None)
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM ltv_orders WHERE customer_id=?",
                    (customer_id,),
                )
                self._conn.commit()
            return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
