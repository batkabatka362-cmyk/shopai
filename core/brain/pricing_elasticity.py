"""Pricing elasticity — estimate demand curve from price/sales history.

The reward_model knows the owner disliked clickbait; the world
model tracks ROAS; but nothing answered the concrete question
"if I raise price from $29 to $32, how many fewer sales?" That's
the classic elasticity question, and getting it right can swing
revenue by double digits.

PricingElasticity fits a log-log regression to (price, units_sold)
observations:

    ln(units) = α + β · ln(price)

β is the *price elasticity of demand*: -0.5 = inelastic, -1 =
unit-elastic, -2 = highly elastic. The fit also yields α, an R² to
gauge fit quality, and 95% bootstrap CI on β.

APIs:

  fit(observations)          → ElasticityFit
  predict_units(fit, price)  → estimated demand at new price
  optimal_price(fit, cost)   → price that maximises (price-cost) ·
                                demand; analytic solution when
                                elasticity < -1, otherwise
                                grid-search fallback
  revenue_at(fit, price)     → price · predicted_units

Fit requires ≥ 3 distinct price points. Degenerate inputs
(all same price, missing units) return a special ``fit.valid=False``
so callers can fall back to cohort defaults. Pure stdlib math.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class PriceObservation:
    price: float
    units_sold: float
    period_days: int = 1

    @property
    def daily_units(self) -> float:
        if self.period_days <= 0:
            return self.units_sold
        return self.units_sold / self.period_days


@dataclass
class ElasticityFit:
    valid: bool
    alpha: float = 0.0           # intercept in log space
    beta: float = 0.0            # elasticity coefficient
    r_squared: float = 0.0
    ci_low: float | None = None
    ci_high: float | None = None
    n_points: int = 0
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "r_squared": round(self.r_squared, 4),
            "ci_low": (None if self.ci_low is None
                        else round(self.ci_low, 4)),
            "ci_high": (None if self.ci_high is None
                         else round(self.ci_high, 4)),
            "n_points": self.n_points,
            "message": self.message,
        }

    @property
    def is_elastic(self) -> bool:
        return self.valid and self.beta < -1.0


# ── Regression ──────────────────────────────────────────────

def _linreg(
    xs: list[float], ys: list[float],
) -> tuple[float, float, float]:
    """Return (alpha, beta, r_squared) via ordinary least squares."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0:
        return my, 0.0, 0.0
    beta = sxy / sxx
    alpha = my - beta * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot <= 0:
        return alpha, beta, 0.0
    ss_res = sum(
        (y - (alpha + beta * x)) ** 2
        for x, y in zip(xs, ys)
    )
    r_squared = 1.0 - ss_res / ss_tot
    return alpha, beta, max(0.0, min(1.0, r_squared))


# ── Fit ─────────────────────────────────────────────────────

def fit(
    observations: Iterable[PriceObservation | dict[str, Any]],
    *,
    bootstrap_samples: int = 200,
    rng: random.Random | None = None,
) -> ElasticityFit:
    obs: list[PriceObservation] = []
    for o in observations:
        if isinstance(o, PriceObservation):
            obs.append(o)
        else:
            obs.append(PriceObservation(
                price=float(o.get("price", 0)),
                units_sold=float(o.get("units_sold", 0)),
                period_days=int(o.get("period_days", 1)),
            ))
    # Drop non-positive prices and zero-unit observations (log undefined)
    obs = [
        o for o in obs
        if o.price > 0 and o.daily_units > 0
    ]
    if len(obs) < 3:
        return ElasticityFit(
            valid=False, n_points=len(obs),
            message="need ≥3 valid observations",
        )
    distinct_prices = {round(o.price, 4) for o in obs}
    if len(distinct_prices) < 2:
        return ElasticityFit(
            valid=False, n_points=len(obs),
            message="need ≥2 distinct prices",
        )
    xs = [math.log(o.price) for o in obs]
    ys = [math.log(o.daily_units) for o in obs]
    alpha, beta, r2 = _linreg(xs, ys)

    # Bootstrap β CI
    ci_low: float | None = None
    ci_high: float | None = None
    if bootstrap_samples > 0 and len(obs) >= 4:
        rng = rng or random.Random()
        betas: list[float] = []
        n = len(obs)
        for _ in range(int(bootstrap_samples)):
            idx = [rng.randrange(n) for _ in range(n)]
            sub_xs = [xs[i] for i in idx]
            sub_ys = [ys[i] for i in idx]
            _, bb, _ = _linreg(sub_xs, sub_ys)
            betas.append(bb)
        betas.sort()
        lo = int(0.025 * len(betas))
        hi = int(0.975 * len(betas))
        ci_low = betas[max(0, lo)]
        ci_high = betas[min(len(betas) - 1, hi)]

    return ElasticityFit(
        valid=True,
        alpha=alpha, beta=beta, r_squared=r2,
        ci_low=ci_low, ci_high=ci_high,
        n_points=len(obs),
        message="ok",
    )


# ── Prediction ──────────────────────────────────────────────

def predict_units(
    fit: ElasticityFit, price: float,
) -> float:
    if not fit.valid or price <= 0:
        return 0.0
    return math.exp(fit.alpha + fit.beta * math.log(price))


def revenue_at(fit: ElasticityFit, price: float) -> float:
    return price * predict_units(fit, price)


def optimal_price(
    fit: ElasticityFit,
    unit_cost: float,
    *,
    min_price: float = 0.01,
    max_price: float = 1_000.0,
    steps: int = 200,
) -> float:
    """Return the price that maximises (price − unit_cost) × units.

    Analytic closed-form when β < -1 (elastic): p* = β · cost /
    (1 + β) yields the profit-maximising price under the log-log
    model. For β ≥ -1 (inelastic) profit keeps rising with price
    — fall back to grid search capped at max_price.
    """
    if not fit.valid:
        return max(unit_cost, min_price)
    if fit.beta < -1:
        star = fit.beta * float(unit_cost) / (1.0 + fit.beta)
        if star > 0:
            return max(min_price, min(max_price, star))
    # Grid search fallback
    best_price = max(min_price, unit_cost)
    best_profit = -float("inf")
    step = (max_price - min_price) / max(1, steps)
    p = min_price
    while p <= max_price:
        units = predict_units(fit, p)
        profit = (p - unit_cost) * units
        if profit > best_profit:
            best_profit = profit
            best_price = p
        p += step
    return best_price
