"""Economic simulator — project revenue / spend / cashflow forward.

offline_sandbox (v6-D5) simulates *plan execution* at the event
level. The owner cares about a higher-level question: "at current
trajectory, what's my cash position in 90 days?" Answering that
requires a revenue model (active launches × ROAS × spend) and a
cost model (ad spend + fixed monthly costs + variable per-sale
cost).

EconomicSimulator composes four inputs:

  • Active launches — each with daily_spend, roas_mean, roas_stdev,
                       days_remaining (None = indefinite).
  • Fixed costs      — subscriptions, salaries, monthly minimums.
  • Variable costs   — per-sale COGS + fulfilment (as pct of rev).
  • Cash runway      — starting balance.

project(horizon_days) runs a daily simulation (or Monte Carlo
with ``n_samples`` > 1) and returns:

  • daily_balances — list[CashPoint] for charting
  • summary        — total revenue, total spend, end balance,
                     lowest point (risk of running out), break-even
                     day if the trajectory is negative.

When ``mode="monte_carlo"``, each day's ROAS is drawn from
Normal(mean, stdev); the simulator returns percentile bands (p10 /
p50 / p90).

Pure stdlib. Deterministic under seeded RNG. No LLM.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Mode = Literal["point", "monte_carlo"]


@dataclass
class LaunchPlan:
    launch_id: str
    daily_spend: float
    roas_mean: float
    roas_stdev: float = 0.0
    days_remaining: int | None = None       # None = runs entire horizon

    def active_on(self, day: int) -> bool:
        if self.days_remaining is None:
            return True
        return day < int(self.days_remaining)


@dataclass
class CostPlan:
    monthly_fixed: float = 0.0
    cogs_pct_of_revenue: float = 0.0        # 0..1
    fulfilment_pct_of_revenue: float = 0.0  # 0..1


@dataclass
class CashPoint:
    day: int
    balance: float
    revenue: float
    spend: float
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "balance": round(self.balance, 2),
            "revenue": round(self.revenue, 2),
            "spend": round(self.spend, 2),
            "p10": None if self.p10 is None else round(self.p10, 2),
            "p50": None if self.p50 is None else round(self.p50, 2),
            "p90": None if self.p90 is None else round(self.p90, 2),
        }


@dataclass
class ProjectionSummary:
    horizon_days: int
    starting_balance: float
    ending_balance: float
    total_revenue: float
    total_spend: float
    min_balance: float
    min_balance_day: int
    break_even_day: int | None = None
    runway_days: int | None = None     # days until balance < 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "starting_balance": round(self.starting_balance, 2),
            "ending_balance": round(self.ending_balance, 2),
            "total_revenue": round(self.total_revenue, 2),
            "total_spend": round(self.total_spend, 2),
            "min_balance": round(self.min_balance, 2),
            "min_balance_day": self.min_balance_day,
            "break_even_day": self.break_even_day,
            "runway_days": self.runway_days,
        }


@dataclass
class Projection:
    summary: ProjectionSummary
    daily: list[CashPoint] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.as_dict(),
            "daily": [p.as_dict() for p in self.daily],
        }


# ── Simulator ───────────────────────────────────────────────

def project(
    launches: Iterable[LaunchPlan],
    costs: CostPlan,
    starting_balance: float,
    horizon_days: int,
    *,
    mode: Mode = "point",
    n_samples: int = 100,
    rng: random.Random | None = None,
) -> Projection:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be > 0")
    launches = list(launches)
    if mode == "monte_carlo" and n_samples > 1:
        return _monte_carlo(
            launches, costs, starting_balance,
            horizon_days, n_samples, rng or random.Random(),
        )
    # Point estimate: mean ROAS, no sampling.
    rng = rng or random.Random()
    daily: list[CashPoint] = []
    balance = float(starting_balance)
    total_rev = 0.0
    total_spend = 0.0
    min_balance = balance
    min_day = 0
    break_even = None
    runway = None
    daily_fixed = float(costs.monthly_fixed) / 30.0
    for day in range(horizon_days):
        day_spend = daily_fixed
        day_rev = 0.0
        for launch in launches:
            if not launch.active_on(day):
                continue
            spend = float(launch.daily_spend)
            rev = spend * float(launch.roas_mean)
            day_spend += spend
            day_spend += rev * float(costs.cogs_pct_of_revenue)
            day_spend += rev * float(costs.fulfilment_pct_of_revenue)
            day_rev += rev
        balance += day_rev - day_spend
        total_rev += day_rev
        total_spend += day_spend
        if balance < min_balance:
            min_balance = balance
            min_day = day
        if balance < 0 and runway is None:
            runway = day
        if break_even is None and (total_rev - total_spend) >= 0 and day > 0:
            break_even = day
        daily.append(CashPoint(
            day=day, balance=balance,
            revenue=day_rev, spend=day_spend,
        ))
    summary = ProjectionSummary(
        horizon_days=horizon_days,
        starting_balance=float(starting_balance),
        ending_balance=balance,
        total_revenue=total_rev,
        total_spend=total_spend,
        min_balance=min_balance,
        min_balance_day=min_day,
        break_even_day=break_even,
        runway_days=runway,
    )
    return Projection(summary=summary, daily=daily)


# ── Monte Carlo ─────────────────────────────────────────────

def _monte_carlo(
    launches: list[LaunchPlan],
    costs: CostPlan,
    starting_balance: float,
    horizon_days: int,
    n_samples: int,
    rng: random.Random,
) -> Projection:
    daily_fixed = float(costs.monthly_fixed) / 30.0
    # For each sample, generate a full trajectory.
    trajectories: list[list[float]] = []
    rev_totals: list[float] = []
    spend_totals: list[float] = []
    for _ in range(n_samples):
        balance = float(starting_balance)
        balances: list[float] = []
        total_rev = 0.0
        total_spend = 0.0
        for day in range(horizon_days):
            day_spend = daily_fixed
            day_rev = 0.0
            for launch in launches:
                if not launch.active_on(day):
                    continue
                spend = float(launch.daily_spend)
                roas = max(
                    0.0,
                    rng.gauss(launch.roas_mean, launch.roas_stdev),
                )
                rev = spend * roas
                day_spend += spend
                day_spend += rev * float(costs.cogs_pct_of_revenue)
                day_spend += rev * float(costs.fulfilment_pct_of_revenue)
                day_rev += rev
            balance += day_rev - day_spend
            balances.append(balance)
            total_rev += day_rev
            total_spend += day_spend
        trajectories.append(balances)
        rev_totals.append(total_rev)
        spend_totals.append(total_spend)
    # Per-day percentiles
    daily: list[CashPoint] = []
    for day in range(horizon_days):
        col = sorted(t[day] for t in trajectories)
        p = lambda q: col[min(len(col) - 1, int(q * len(col)))]
        daily.append(CashPoint(
            day=day,
            balance=p(0.5),
            revenue=0.0, spend=0.0,
            p10=p(0.1), p50=p(0.5), p90=p(0.9),
        ))
    # Summary uses medians for rev/spend/end balance.
    end_balances = sorted(t[-1] for t in trajectories)
    min_per_sample = [min(t) for t in trajectories]
    min_balance = sorted(min_per_sample)[len(min_per_sample) // 2]
    min_day = 0
    for day, point in enumerate(daily):
        if point.balance == min_balance:
            min_day = day
            break
    rev_totals.sort(); spend_totals.sort()
    median = lambda xs: xs[len(xs) // 2]
    summary = ProjectionSummary(
        horizon_days=horizon_days,
        starting_balance=float(starting_balance),
        ending_balance=end_balances[len(end_balances) // 2],
        total_revenue=median(rev_totals),
        total_spend=median(spend_totals),
        min_balance=min_balance,
        min_balance_day=min_day,
        break_even_day=None,    # less meaningful under uncertainty
        runway_days=next(
            (d for d, pt in enumerate(daily) if pt.balance < 0),
            None,
        ),
    )
    return Projection(summary=summary, daily=daily)
