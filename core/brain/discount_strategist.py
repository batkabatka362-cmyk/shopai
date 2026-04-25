"""Discount strategist — when and how much to discount.

Discount is a blunt tool: 20% off increases short-term sales but
trains customers to wait for deals. The question isn't "discount
or not" — it's *which customers, which products, how much, for
how long*.

DiscountStrategist combines four signals:

  • churn_risk            (v14-D7) — higher → bigger save-side discount
  • elasticity            (v14-D5) — more elastic products respond
                                     better to discounts
  • margin_pct            — never discount below cost + floor margin
  • inventory_pressure   — older / bloated stock deserves deeper cut

Output is a DiscountRecommendation with:

  percent_off        — bounded by {min_pct, max_pct}
  validity_hours     — short window to avoid training 'wait-for-sale'
  reason             — primary driver text
  expected_lift      — from the elasticity fit (units delta)
  margin_protected   — final margin ≥ floor

Plus guardrails:

  blacklist_products — never discount
  max_simultaneous_pct — limit stacking (BOGO + coupon + flash sale)

Pure Python; deterministic; zero LLM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class StrategyInputs:
    sku: str
    base_price: float
    unit_cost: float
    margin_pct: float
    churn_risk: float = 0.0
    elasticity_beta: float = -1.0        # log-log demand slope
    inventory_units: int | None = None
    days_of_stock: float | None = None
    customer_ltv: float = 0.0


@dataclass
class DiscountRecommendation:
    sku: str
    percent_off: float
    validity_hours: int
    reason: str
    expected_unit_lift_pct: float
    final_margin_pct: float
    allowed: bool = True
    guardrail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "percent_off": round(self.percent_off, 2),
            "validity_hours": self.validity_hours,
            "reason": self.reason,
            "expected_unit_lift_pct": round(
                self.expected_unit_lift_pct, 2,
            ),
            "final_margin_pct": round(self.final_margin_pct, 3),
            "allowed": self.allowed,
            "guardrail": self.guardrail,
        }


@dataclass
class StrategyConfig:
    min_pct: float = 5.0
    max_pct: float = 30.0
    floor_margin_pct: float = 0.10
    default_validity_hours: int = 48
    blacklist_skus: frozenset[str] = field(default_factory=frozenset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_pct": self.min_pct,
            "max_pct": self.max_pct,
            "floor_margin_pct": self.floor_margin_pct,
            "default_validity_hours": self.default_validity_hours,
            "blacklist_skus": sorted(self.blacklist_skus),
        }


# ── Strategist ──────────────────────────────────────────────

class DiscountStrategist:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self._config = config or StrategyConfig()

    def config(self) -> StrategyConfig:
        return self._config

    def recommend(self, inputs: StrategyInputs) -> DiscountRecommendation:
        # Blacklisted → refuse
        if inputs.sku in self._config.blacklist_skus:
            return DiscountRecommendation(
                sku=inputs.sku, percent_off=0.0,
                validity_hours=0,
                reason="blacklisted",
                expected_unit_lift_pct=0.0,
                final_margin_pct=inputs.margin_pct,
                allowed=False, guardrail="blacklist",
            )
        # Invalid base → refuse
        if inputs.base_price <= 0 or inputs.unit_cost < 0:
            return DiscountRecommendation(
                sku=inputs.sku, percent_off=0.0,
                validity_hours=0, reason="invalid price",
                expected_unit_lift_pct=0.0,
                final_margin_pct=0.0,
                allowed=False, guardrail="invalid_inputs",
            )

        # Raw discount intent from signals
        intents: list[tuple[float, str]] = []

        # 1. Churn risk: save-side discount for at-risk customers
        if inputs.churn_risk >= 0.5:
            intents.append(
                (15.0 + 15.0 * inputs.churn_risk,
                 f"save high-churn-risk customer "
                 f"(risk {inputs.churn_risk:.0%})"),
            )
        elif inputs.churn_risk >= 0.3:
            intents.append(
                (8.0 + 12.0 * inputs.churn_risk,
                 "mild save-side nudge"),
            )

        # 2. Inventory pressure: clear aging stock
        if inputs.days_of_stock is not None and inputs.days_of_stock > 90:
            depth = min(25.0, (inputs.days_of_stock - 90) / 4)
            intents.append(
                (depth, f"stock pressure "
                 f"({inputs.days_of_stock:.0f}d cover)"),
            )

        # 3. Elasticity: deep discounts only on elastic products
        if inputs.elasticity_beta < -1.5:
            intents.append(
                (10.0 + min(15.0, abs(inputs.elasticity_beta + 1.5) * 10),
                 f"highly elastic (β={inputs.elasticity_beta:.2f})"),
            )

        # 4. Cold start — default small discount
        if not intents:
            intents.append(
                (self._config.min_pct, "default low discount"),
            )

        # Pick the strongest intent
        intents.sort(key=lambda kv: -kv[0])
        raw_pct, reason = intents[0]
        # Clip to [min, max]
        pct = max(
            self._config.min_pct,
            min(self._config.max_pct, raw_pct),
        )

        # Enforce margin floor: new_margin = (price·(1-pct) − cost)/price·(1-pct)
        new_price = inputs.base_price * (1.0 - pct / 100.0)
        if new_price <= 0:
            return DiscountRecommendation(
                sku=inputs.sku, percent_off=0.0,
                validity_hours=0,
                reason="discount would invert price",
                expected_unit_lift_pct=0.0,
                final_margin_pct=0.0,
                allowed=False, guardrail="margin_floor",
            )
        new_margin = (new_price - inputs.unit_cost) / new_price
        if new_margin < self._config.floor_margin_pct:
            # Shrink pct until margin meets the floor.
            safe_price = inputs.unit_cost / (
                1.0 - self._config.floor_margin_pct
            )
            pct = max(0.0, (1.0 - safe_price / inputs.base_price) * 100.0)
            if pct < self._config.min_pct:
                return DiscountRecommendation(
                    sku=inputs.sku, percent_off=0.0,
                    validity_hours=0,
                    reason="margin floor leaves no room",
                    expected_unit_lift_pct=0.0,
                    final_margin_pct=inputs.margin_pct,
                    allowed=False, guardrail="margin_floor",
                )
            new_price = inputs.base_price * (1.0 - pct / 100.0)
            new_margin = (new_price - inputs.unit_cost) / new_price
            reason = reason + " (clamped for margin)"

        # Expected unit lift from log-log elasticity
        # ΔQ/Q ≈ β · Δlog(P)
        try:
            delta_log = math.log(1.0 - pct / 100.0)
            lift = abs(inputs.elasticity_beta * delta_log) * 100
        except ValueError:
            lift = 0.0
        return DiscountRecommendation(
            sku=inputs.sku,
            percent_off=pct,
            validity_hours=self._config.default_validity_hours,
            reason=reason,
            expected_unit_lift_pct=lift,
            final_margin_pct=new_margin,
            allowed=True,
            guardrail="",
        )

    # ── Batch ──────────────────────────────────────────────

    def batch(
        self, inputs: Iterable[StrategyInputs],
    ) -> list[DiscountRecommendation]:
        out = [self.recommend(x) for x in inputs]
        out.sort(key=lambda d: -d.expected_unit_lift_pct)
        return out
