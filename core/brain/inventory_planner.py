"""Inventory planner — reorder point + safety stock.

Running out of stock is one of the most expensive failures in
e-commerce: every stockout loses a sale AND upsets the customer.
Ordering too early kills cashflow. The classical fix is two
numbers:

  reorder_point = lead_time_days × daily_demand + safety_stock
  safety_stock  = z_score × σ_demand × sqrt(lead_time_days)

Where z_score maps a service level: 95% = 1.65, 98% = 2.05,
99% = 2.33. σ_demand is the standard deviation of daily demand
observed historically.

InventoryPlanner offers:

  reorder_point(daily_mean, daily_std, lead_time_days, service)
  should_reorder(sku, on_hand, daily_mean, daily_std, lead_time,
                  service)          → bool + suggested quantity
  eoq(annual_demand, ordering_cost, holding_cost_per_unit)
      — economic order quantity: sqrt(2 D S / H)
  stockout_risk(on_hand, daily_mean, daily_std, days_until_next)
      — probability of running out before replenishment

Pure stdlib stats (normal CDF via erf). Zero LLM. Deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# Service-level → z-score table
_Z_SCORES: dict[float, float] = {
    0.50: 0.00,
    0.80: 0.84,
    0.85: 1.04,
    0.90: 1.28,
    0.95: 1.65,
    0.97: 1.88,
    0.98: 2.05,
    0.99: 2.33,
    0.995: 2.58,
    0.999: 3.09,
}


def _z_for(service_level: float) -> float:
    """Interpolate z-score from the table. Clamps to table bounds."""
    service_level = max(0.50, min(0.999, float(service_level)))
    keys = sorted(_Z_SCORES.keys())
    if service_level in _Z_SCORES:
        return _Z_SCORES[service_level]
    # Linear interpolation
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= service_level <= hi:
            t = (service_level - lo) / (hi - lo)
            return _Z_SCORES[lo] + t * (_Z_SCORES[hi] - _Z_SCORES[lo])
    return _Z_SCORES[keys[-1]]


@dataclass
class ReorderDecision:
    sku: str
    should_reorder: bool
    reorder_point: float
    on_hand: float
    suggested_quantity: float
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "should_reorder": self.should_reorder,
            "reorder_point": round(self.reorder_point, 2),
            "on_hand": round(self.on_hand, 2),
            "suggested_quantity": round(self.suggested_quantity, 2),
            "rationale": self.rationale,
        }


# ── Core math ───────────────────────────────────────────────

def safety_stock(
    daily_std: float, lead_time_days: float,
    service_level: float = 0.95,
) -> float:
    if daily_std <= 0 or lead_time_days <= 0:
        return 0.0
    z = _z_for(service_level)
    return z * float(daily_std) * math.sqrt(float(lead_time_days))


def reorder_point(
    daily_mean: float,
    daily_std: float,
    lead_time_days: float,
    service_level: float = 0.95,
) -> float:
    base = max(0.0, float(daily_mean)) * max(0.0, float(lead_time_days))
    return base + safety_stock(daily_std, lead_time_days, service_level)


def eoq(
    annual_demand: float,
    ordering_cost: float,
    holding_cost_per_unit: float,
) -> float:
    """Economic order quantity: Q* = sqrt(2 D S / H)."""
    if (annual_demand <= 0 or ordering_cost <= 0
            or holding_cost_per_unit <= 0):
        return 0.0
    return math.sqrt(
        2.0 * float(annual_demand) * float(ordering_cost)
        / float(holding_cost_per_unit),
    )


# ── Stockout probability ────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def stockout_risk(
    on_hand: float,
    daily_mean: float,
    daily_std: float,
    days_until_next: float,
) -> float:
    """P(cumulative demand over days_until_next exceeds on_hand).

    Treats cumulative demand as Normal(μ·days, σ·sqrt(days))."""
    if days_until_next <= 0 or daily_mean <= 0:
        return 0.0
    mu = float(daily_mean) * float(days_until_next)
    sigma = float(daily_std) * math.sqrt(float(days_until_next))
    if sigma <= 0:
        return 1.0 if on_hand < mu else 0.0
    z = (float(on_hand) - mu) / sigma
    return max(0.0, min(1.0, 1.0 - _norm_cdf(z)))


# ── Decision ────────────────────────────────────────────────

def should_reorder(
    sku: str,
    on_hand: float,
    daily_mean: float,
    daily_std: float,
    lead_time_days: float,
    service_level: float = 0.95,
    target_days_cover: float = 30.0,
) -> ReorderDecision:
    rop = reorder_point(
        daily_mean, daily_std, lead_time_days, service_level,
    )
    suggested = (float(daily_mean) * float(target_days_cover)
                  + safety_stock(daily_std, lead_time_days, service_level)
                  - float(on_hand))
    suggested = max(0.0, suggested)
    trigger = on_hand <= rop
    rationale = (
        f"on_hand={on_hand:.1f} vs ROP={rop:.1f}"
        f" (lead={lead_time_days}d, service={service_level:.0%})"
    )
    return ReorderDecision(
        sku=sku,
        should_reorder=trigger,
        reorder_point=rop,
        on_hand=float(on_hand),
        suggested_quantity=suggested,
        rationale=rationale,
    )


# ── Batch helper ────────────────────────────────────────────

@dataclass
class SKUStats:
    sku: str
    on_hand: float
    daily_mean: float
    daily_std: float
    lead_time_days: float


def batch_decisions(
    skus: list[SKUStats],
    service_level: float = 0.95,
    target_days_cover: float = 30.0,
) -> list[ReorderDecision]:
    decisions = [
        should_reorder(
            sku=s.sku, on_hand=s.on_hand,
            daily_mean=s.daily_mean, daily_std=s.daily_std,
            lead_time_days=s.lead_time_days,
            service_level=service_level,
            target_days_cover=target_days_cover,
        )
        for s in skus
    ]
    # Most-urgent first (largest gap below ROP)
    decisions.sort(
        key=lambda d: -(d.reorder_point - d.on_hand),
    )
    return decisions
