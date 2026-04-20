"""Launch simulator — Monte Carlo pre-flight profit projection.

Sprint 3 S3-9 (P2, L8 in docs/AGI_STACK.md). Before a
``CampaignActivator`` flips PAUSED → ACTIVE on a real Meta Ads
campaign, the brain should know the *expected* profit and the
probability of breaking even. That's the job of this module.

Distinct from neighbours:
  * ``core/brain/economic_simulator`` projects *portfolio* cash-flow
    across many active launches — weekly/monthly horizon.
  * ``engines/market_simulator`` is an adoption-curve scenario
    comparator for what-if analysis.
  * This module answers a *single-product pre-flight* question:
    "if I burn $X/day of ads at this candidate for N days, what
    does my p25/p50/p75 profit look like?"

Model (intentionally simple so it's auditable):

    impressions ≈ daily_budget / cpc_mean
    orders      ≈ impressions × cvr
    gross       = (price - cost) × orders × (1 - refund_rate)
    profit      = gross - daily_budget

cvr and cpc are sampled per trial from Normal(mean, stdev),
clamped to sane ranges. Run ``n_trials`` (default 1000) and emit
p25/p50/p75/mean profit + break-even probability + expected ROAS.

Pure stdlib (random + statistics). Seeded for determinism — same
seed + same candidate → same projection. LLM-free. Zero cost.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_TRIALS = 1000
_MIN_CVR = 0.001
_MAX_CVR = 0.30
_MIN_CPC = 0.01
_MAX_CPC = 20.0


@dataclass
class LaunchCandidate:
    """A product + ad budget proposal under evaluation."""
    cost: float                     # COGS + fulfilment, per unit
    price: float                    # retail sell price
    daily_budget_usd: float         # ad spend per day
    days: int = 3                   # horizon before re-evaluate
    est_cvr_mean: float = 0.02      # 2% purchase conversion default
    est_cvr_stddev: float = 0.01
    est_cpc_mean: float = 1.20      # $1.20 CPC default
    est_cpc_stddev: float = 0.40
    refund_rate: float = 0.05       # 5% refund/return
    fixed_cost_per_day: float = 0.0  # platform fees etc.

    def __post_init__(self) -> None:
        for name in (
            "cost", "price", "daily_budget_usd",
            "est_cvr_mean", "est_cpc_mean",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(
                    f"{name} must be ≥ 0",
                )
        if self.days <= 0:
            raise ValueError("days must be > 0")
        if not 0.0 <= self.refund_rate <= 1.0:
            raise ValueError(
                "refund_rate must be in [0, 1]",
            )
        if self.est_cvr_stddev < 0 or self.est_cpc_stddev < 0:
            raise ValueError(
                "stddev must be ≥ 0",
            )
        if self.price <= self.cost:
            # Not fatal — simulator will return losing distribution —
            # but mark it so the caller can short-circuit.
            pass

    def margin_ratio(self) -> float:
        if self.price <= 0:
            return 0.0
        return max(0.0, (self.price - self.cost) / self.price)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cost": round(self.cost, 4),
            "price": round(self.price, 4),
            "daily_budget_usd": round(
                self.daily_budget_usd, 2,
            ),
            "days": self.days,
            "est_cvr_mean": round(self.est_cvr_mean, 6),
            "est_cvr_stddev": round(
                self.est_cvr_stddev, 6,
            ),
            "est_cpc_mean": round(self.est_cpc_mean, 4),
            "est_cpc_stddev": round(
                self.est_cpc_stddev, 4,
            ),
            "refund_rate": round(self.refund_rate, 4),
            "fixed_cost_per_day": round(
                self.fixed_cost_per_day, 4,
            ),
            "margin_ratio": round(self.margin_ratio(), 4),
        }


@dataclass
class LaunchProjection:
    """Monte Carlo outcome distribution for a candidate."""
    candidate: LaunchCandidate
    n_trials: int
    profit_p25: float
    profit_p50: float
    profit_p75: float
    profit_mean: float
    profit_stddev: float
    break_even_prob: float          # fraction of trials where profit > 0
    expected_orders: float
    expected_roas: float            # revenue / ad spend
    verdict: str                    # "go" | "caution" | "stand_down"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "n_trials": self.n_trials,
            "profit_p25": round(self.profit_p25, 2),
            "profit_p50": round(self.profit_p50, 2),
            "profit_p75": round(self.profit_p75, 2),
            "profit_mean": round(self.profit_mean, 2),
            "profit_stddev": round(
                self.profit_stddev, 2,
            ),
            "break_even_prob": round(
                self.break_even_prob, 4,
            ),
            "expected_orders": round(
                self.expected_orders, 2,
            ),
            "expected_roas": round(
                self.expected_roas, 3,
            ),
            "verdict": self.verdict,
            "reason": self.reason,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _percentile(samples: list[float], pct: float) -> float:
    """Simple percentile from a sorted sample list.

    Doesn't use ``statistics.quantiles`` because the Python version
    of that function requires n >= 2 and rounds oddly at edges.
    """
    if not samples:
        return 0.0
    srt = sorted(samples)
    k = (len(srt) - 1) * _clamp(pct, 0.0, 1.0)
    lo = int(k)
    hi = min(lo + 1, len(srt) - 1)
    frac = k - lo
    return srt[lo] + (srt[hi] - srt[lo]) * frac


def simulate_launch(
    candidate: LaunchCandidate,
    *,
    n_trials: int = _DEFAULT_TRIALS,
    seed: int | None = 1337,
    break_even_floor: float = 0.60,
    profit_floor_usd: float = 0.0,
) -> LaunchProjection:
    """Run a Monte Carlo projection on a launch candidate.

    Args:
      candidate:         the proposal.
      n_trials:          samples to draw (default 1000).
      seed:              RNG seed; None for OS randomness.
      break_even_floor:  minimum break-even probability to earn
                         verdict='go' (default 0.60).
      profit_floor_usd:  minimum median profit required to earn
                         verdict='go' (default $0 — non-negative).

    Returns:
      ``LaunchProjection`` with profit percentiles + verdict.
    """
    if n_trials <= 0:
        raise ValueError("n_trials must be > 0")
    if not 0.0 <= break_even_floor <= 1.0:
        raise ValueError(
            "break_even_floor must be in [0, 1]",
        )
    rng = random.Random(seed)
    c = candidate
    spend = c.daily_budget_usd * c.days
    fixed = c.fixed_cost_per_day * c.days

    profits: list[float] = []
    orders_per_trial: list[float] = []
    revenue_total = 0.0

    for _ in range(n_trials):
        cpc = _clamp(
            rng.gauss(c.est_cpc_mean, c.est_cpc_stddev),
            _MIN_CPC, _MAX_CPC,
        )
        cvr = _clamp(
            rng.gauss(c.est_cvr_mean, c.est_cvr_stddev),
            _MIN_CVR, _MAX_CVR,
        )
        impressions = (
            (c.daily_budget_usd / cpc) * c.days
            if cpc > 0 else 0.0
        )
        orders = impressions * cvr
        gross = (
            (c.price - c.cost)
            * orders
            * (1.0 - c.refund_rate)
        )
        profit = gross - spend - fixed
        profits.append(profit)
        orders_per_trial.append(orders)
        revenue_total += c.price * orders * (
            1.0 - c.refund_rate
        )

    profit_mean = sum(profits) / len(profits)
    profit_stddev = (
        statistics.pstdev(profits) if len(profits) > 1 else 0.0
    )
    p25 = _percentile(profits, 0.25)
    p50 = _percentile(profits, 0.50)
    p75 = _percentile(profits, 0.75)
    break_even = (
        sum(1 for p in profits if p > 0) / len(profits)
    )
    expected_orders = (
        sum(orders_per_trial) / len(orders_per_trial)
    )
    expected_roas = (
        (revenue_total / len(profits)) / spend
        if spend > 0 else 0.0
    )

    # Verdict logic
    if c.price <= c.cost:
        verdict = "stand_down"
        reason = (
            f"price ${c.price:.2f} ≤ cost ${c.cost:.2f}"
        )
    elif break_even < break_even_floor * 0.5:
        verdict = "stand_down"
        reason = (
            f"break-even prob {break_even:.0%} << floor "
            f"{break_even_floor:.0%}"
        )
    elif (
        break_even < break_even_floor
        or p50 < profit_floor_usd
    ):
        verdict = "caution"
        reason = (
            f"break-even {break_even:.0%} / median "
            f"${p50:.2f}"
        )
    else:
        verdict = "go"
        reason = (
            f"break-even {break_even:.0%}, median "
            f"${p50:.2f}"
        )

    return LaunchProjection(
        candidate=c,
        n_trials=n_trials,
        profit_p25=p25,
        profit_p50=p50,
        profit_p75=p75,
        profit_mean=profit_mean,
        profit_stddev=profit_stddev,
        break_even_prob=break_even,
        expected_orders=expected_orders,
        expected_roas=expected_roas,
        verdict=verdict,
        reason=reason,
    )
