"""LTV estimator — predict customer lifetime value from early signal.

A customer's first order tells you very little by itself. Their
first-order value, repeat rate, and inter-purchase gap together
tell you how much they'll spend over the next 12/24 months.
Without an LTV estimate, the brain overspends to acquire low-
value customers and under-rewards high-value ones.

LTVEstimator implements a lightweight BG/NBD-inspired predictor:

  alive_prob(t)    — probability the customer hasn't churned
                     by time t (based on recency and gap)
  expected_orders(horizon_days) — expected repeat orders in the
                     window, using the customer's observed
                     frequency and a simple Poisson rate estimate
  ltv(horizon_days) — sum of (first order value × alive_prob) +
                      (expected_orders × avg_order_value)

Cohort fit: ``fit_cohort(records)`` aggregates a cohort's orders
to produce population-level defaults (average first-order value,
average repeat rate, average gap) so a new customer with one
order can still be scored using the cohort's prior.

Pure stdlib math. Deterministic. No LLM.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class CustomerRecord:
    customer_id: str
    first_order_ts: float
    last_order_ts: float
    order_count: int
    total_revenue: float

    @property
    def tenure_days(self) -> float:
        return max(0.0, (self.last_order_ts - self.first_order_ts) / 86_400)

    @property
    def avg_order_value(self) -> float:
        if self.order_count <= 0:
            return 0.0
        return self.total_revenue / self.order_count

    @property
    def inter_order_gap_days(self) -> float:
        """Mean gap between consecutive orders (approximate)."""
        if self.order_count <= 1:
            return 0.0
        return self.tenure_days / (self.order_count - 1)


@dataclass
class CohortStats:
    n_customers: int = 0
    avg_first_order_value: float = 0.0
    avg_order_value: float = 0.0
    avg_repeat_rate: float = 0.0       # fraction of customers with ≥2 orders
    avg_inter_gap_days: float = 0.0    # among repeat customers

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_customers": self.n_customers,
            "avg_first_order_value": round(self.avg_first_order_value, 2),
            "avg_order_value": round(self.avg_order_value, 2),
            "avg_repeat_rate": round(self.avg_repeat_rate, 3),
            "avg_inter_gap_days": round(self.avg_inter_gap_days, 2),
        }


@dataclass
class LTVEstimate:
    customer_id: str
    horizon_days: int
    alive_prob: float
    expected_orders: float
    predicted_revenue: float
    avg_order_value: float
    inter_gap_days: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "horizon_days": self.horizon_days,
            "alive_prob": round(self.alive_prob, 3),
            "expected_orders": round(self.expected_orders, 2),
            "predicted_revenue": round(self.predicted_revenue, 2),
            "avg_order_value": round(self.avg_order_value, 2),
            "inter_gap_days": round(self.inter_gap_days, 2),
        }


# ── Cohort fit ──────────────────────────────────────────────

def fit_cohort(records: Iterable[CustomerRecord]) -> CohortStats:
    records = list(records)
    n = len(records)
    if n == 0:
        return CohortStats()
    first_values = [
        r.total_revenue / r.order_count
        if r.order_count > 0 else 0.0
        for r in records
    ]
    order_values = [r.avg_order_value for r in records]
    repeaters = [r for r in records if r.order_count >= 2]
    repeat_rate = len(repeaters) / n
    if repeaters:
        inter_gap = sum(r.inter_order_gap_days for r in repeaters) / len(repeaters)
    else:
        inter_gap = 0.0
    return CohortStats(
        n_customers=n,
        avg_first_order_value=sum(first_values) / n,
        avg_order_value=sum(order_values) / n,
        avg_repeat_rate=repeat_rate,
        avg_inter_gap_days=inter_gap,
    )


# ── Estimator ──────────────────────────────────────────────

class LTVEstimator:
    def __init__(
        self,
        cohort: CohortStats | None = None,
    ) -> None:
        self._cohort = cohort or CohortStats(
            n_customers=0,
            avg_first_order_value=30.0,
            avg_order_value=30.0,
            avg_repeat_rate=0.2,
            avg_inter_gap_days=45.0,
        )

    # ── Fit ────────────────────────────────────────────────

    def fit(self, records: Iterable[CustomerRecord]) -> CohortStats:
        self._cohort = fit_cohort(records)
        return self._cohort

    def cohort(self) -> CohortStats:
        return self._cohort

    # ── Alive probability ─────────────────────────────────

    def alive_prob(
        self,
        record: CustomerRecord,
        now_ts: float | None = None,
    ) -> float:
        now = now_ts or time.time()
        days_since_last = max(
            0.0, (now - record.last_order_ts) / 86_400,
        )
        gap = (
            record.inter_order_gap_days
            if record.order_count > 1
            else max(1.0, self._cohort.avg_inter_gap_days)
        )
        # Simple geometric-decay model: alive = exp(−days_since_last / gap)
        # Clamped so single-order customers aren't instantly dead.
        return max(0.01, min(1.0, math.exp(-days_since_last / max(gap, 1.0))))

    # ── Expected orders ───────────────────────────────────

    def expected_orders(
        self,
        record: CustomerRecord,
        horizon_days: int,
        now_ts: float | None = None,
    ) -> float:
        if horizon_days <= 0:
            return 0.0
        if record.order_count <= 1:
            # Use cohort prior: fraction of 1-order customers who
            # buy again × horizon / avg_gap.
            if self._cohort.avg_repeat_rate <= 0:
                return 0.0
            return (
                self._cohort.avg_repeat_rate
                * horizon_days
                / max(1.0, self._cohort.avg_inter_gap_days)
            )
        # Poisson rate estimate from observed gap.
        gap = max(1.0, record.inter_order_gap_days)
        rate = 1.0 / gap
        alive = self.alive_prob(record, now_ts=now_ts)
        return alive * rate * horizon_days

    # ── LTV ────────────────────────────────────────────────

    def ltv(
        self,
        record: CustomerRecord,
        horizon_days: int = 365,
        now_ts: float | None = None,
    ) -> LTVEstimate:
        alive = self.alive_prob(record, now_ts=now_ts)
        avg = (record.avg_order_value
                if record.order_count > 0
                else self._cohort.avg_first_order_value)
        if record.order_count <= 1:
            avg = max(avg, self._cohort.avg_order_value)
        future_orders = self.expected_orders(
            record, horizon_days, now_ts=now_ts,
        )
        predicted_revenue = future_orders * avg
        return LTVEstimate(
            customer_id=record.customer_id,
            horizon_days=horizon_days,
            alive_prob=alive,
            expected_orders=future_orders,
            predicted_revenue=predicted_revenue,
            avg_order_value=avg,
            inter_gap_days=(
                record.inter_order_gap_days
                if record.order_count > 1
                else self._cohort.avg_inter_gap_days
            ),
        )
