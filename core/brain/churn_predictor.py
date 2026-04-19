"""Churn predictor — flag customers about to stop buying.

LTV estimator (v14-D4) predicts expected spend assuming the
customer stays alive. Churn prediction answers the inverse
question: which customers are *most likely* to defect, now? Give
the brain a prioritised list and it can trigger a save-campaign
(discount code, personal email) only for the segment that
matters.

Method — Recency-Frequency-Monetary (RFM) scoring combined with
cohort-relative percentiles:

  • Recency    — days since last order (lower = better)
  • Frequency  — total order count (higher = better)
  • Monetary   — total revenue (higher = better)

Each customer gets a per-axis 1-5 score (1 = worst, 5 = best)
based on their cohort quintile. Churn risk = f(recency, frequency)
with weights tuned so "stale heavy buyer" outranks "stale casual".
Monetary still influences *priority* (save a £3k customer first).

Also offers survival_curve(records, horizon_days) — the fraction
of a cohort predicted alive at each future day, computed from
recency decay × frequency.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class CustomerRecord:
    customer_id: str
    last_order_ts: float
    order_count: int
    total_revenue: float
    first_order_ts: float | None = None

    def recency_days(self, now_ts: float | None = None) -> float:
        now = now_ts or time.time()
        return max(0.0, (now - self.last_order_ts) / 86_400)

    def tenure_days(self, now_ts: float | None = None) -> float:
        if self.first_order_ts is None:
            return 0.0
        now = now_ts or time.time()
        return max(0.0, (now - self.first_order_ts) / 86_400)

    def avg_gap_days(self, now_ts: float | None = None) -> float:
        if self.order_count <= 1 or self.first_order_ts is None:
            return 0.0
        span = self.tenure_days(now_ts)
        return span / max(1, self.order_count - 1)


@dataclass
class ChurnScore:
    customer_id: str
    recency_score: int              # 1..5
    frequency_score: int            # 1..5
    monetary_score: int             # 1..5
    churn_risk: float               # 0..1, 1 = most likely to churn
    save_priority: float            # 0..1, 1 = save first
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "recency_score": self.recency_score,
            "frequency_score": self.frequency_score,
            "monetary_score": self.monetary_score,
            "churn_risk": round(self.churn_risk, 3),
            "save_priority": round(self.save_priority, 3),
            "rationale": self.rationale,
        }


# ── Quintile helpers ────────────────────────────────────────

def _quintile_score(
    value: float, sorted_values: list[float], ascending: bool,
) -> int:
    """Return an integer 1-5 where 1=worst, 5=best. When ascending
    is True, lower values are better (e.g. recency)."""
    if not sorted_values:
        return 3
    n = len(sorted_values)
    # Find rank (0..n-1) of this value
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    rank = lo
    percentile = rank / max(1, n - 1)
    # percentile 0..1; in ascending=True low percentile = better → 5
    if ascending:
        # rank 0 → best
        return max(1, 5 - int(percentile * 5))
    # Higher value is better → rank n-1 = 5
    return min(5, 1 + int(percentile * 5))


# ── Predictor ───────────────────────────────────────────────

def score_cohort(
    records: Iterable[CustomerRecord],
    *,
    now_ts: float | None = None,
    churn_threshold_days: float | None = None,
) -> list[ChurnScore]:
    records = list(records)
    if not records:
        return []
    recencies = sorted(r.recency_days(now_ts) for r in records)
    frequencies = sorted(r.order_count for r in records)
    monetaries = sorted(r.total_revenue for r in records)
    out: list[ChurnScore] = []
    for r in records:
        rec = r.recency_days(now_ts)
        rec_score = _quintile_score(
            rec, recencies, ascending=True,
        )
        freq_score = _quintile_score(
            r.order_count, frequencies, ascending=False,
        )
        mon_score = _quintile_score(
            r.total_revenue, monetaries, ascending=False,
        )
        risk = _churn_risk(r, rec, churn_threshold_days)
        save_priority = risk * (mon_score / 5.0)
        out.append(ChurnScore(
            customer_id=r.customer_id,
            recency_score=rec_score,
            frequency_score=freq_score,
            monetary_score=mon_score,
            churn_risk=risk,
            save_priority=save_priority,
            rationale=_rationale(rec_score, freq_score, mon_score, risk),
        ))
    out.sort(key=lambda s: -s.save_priority)
    return out


def _churn_risk(
    record: CustomerRecord,
    recency_days: float,
    override_threshold: float | None,
) -> float:
    """0..1 churn probability. Exponential decay scaled by the
    customer's observed inter-order gap (or a cohort default)."""
    gap = record.avg_gap_days()
    if gap <= 0:
        # Single-order customer: use override threshold or 60 days.
        gap = override_threshold or 60.0
    # Risk doubles after 2 gaps, saturates near 1 at 4 gaps.
    ratio = recency_days / max(1.0, gap)
    return max(0.0, min(1.0, 1.0 - math.exp(-0.5 * ratio)))


def _rationale(rec: int, freq: int, mon: int, risk: float) -> str:
    bits = [f"R={rec}", f"F={freq}", f"M={mon}",
             f"risk={risk:.0%}"]
    if rec <= 2 and freq >= 4:
        bits.append("stale heavy-buyer — save now")
    elif rec <= 2 and mon >= 4:
        bits.append("stale high-value — save now")
    elif rec >= 4:
        bits.append("recent — safe")
    return "; ".join(bits)


# ── Survival curve ──────────────────────────────────────────

def survival_curve(
    records: Iterable[CustomerRecord],
    horizon_days: int,
    *,
    now_ts: float | None = None,
) -> list[tuple[int, float]]:
    """Fraction of the cohort predicted alive at each day from 0 to
    horizon_days. Returns a list of (day, fraction_alive)."""
    records = list(records)
    if not records or horizon_days <= 0:
        return [(0, 1.0)]
    out: list[tuple[int, float]] = []
    for day in range(0, horizon_days + 1):
        alive = 0.0
        for r in records:
            rec = r.recency_days(now_ts) + day
            gap = r.avg_gap_days() or 60.0
            alive_prob = math.exp(-0.5 * (rec / max(1.0, gap)))
            alive += max(0.0, min(1.0, alive_prob))
        out.append((day, alive / len(records)))
    return out


# ── Save-campaign targeting ─────────────────────────────────

def target_for_save_campaign(
    records: Iterable[CustomerRecord],
    *,
    top_k: int = 100,
    min_churn_risk: float = 0.4,
    now_ts: float | None = None,
) -> list[ChurnScore]:
    scored = score_cohort(records, now_ts=now_ts)
    filtered = [s for s in scored if s.churn_risk >= min_churn_risk]
    return filtered[:top_k]
