"""Shipping optimizer — cheapest carrier that meets SLA.

Flat-rate shipping loses money on heavy packages and overcharges
customers on light ones. Picking the right carrier per (weight,
destination, SLA) can shave 20%+ off ship cost. The math is
straightforward but tedious — a rule engine nails it.

ShippingOptimizer evaluates a package against a set of carrier
rate cards and returns the cheapest option that:

  • accepts the weight (within carrier bounds)
  • covers the destination zone
  • meets the desired SLA (overnight / 2day / ground)

Each Carrier declares tier-by-tier rates, zone coverage, and SLA
days. Additional fees (fuel surcharge, residential delivery, DIM
weight penalty) apply multiplicatively.

APIs:

  add_carrier(carrier)
  best_option(package) → Quote or None
  all_options(package) → QuoteResult (options + rejected reasons)
  cheapest_per_carrier(package)

Pure stdlib math. Deterministic. No external deps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


SLA = Literal["overnight", "two_day", "ground"]


@dataclass
class RateTier:
    max_weight_kg: float
    price_usd: float


@dataclass
class Carrier:
    name: str
    tiers: list[RateTier]
    zones: frozenset[str]
    sla: SLA
    fuel_surcharge_pct: float = 0.0
    residential_fee_usd: float = 0.0
    dim_weight_divisor: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sla": self.sla,
            "zones": sorted(self.zones),
            "fuel_surcharge_pct": self.fuel_surcharge_pct,
            "residential_fee_usd": self.residential_fee_usd,
            "dim_weight_divisor": self.dim_weight_divisor,
            "tiers": [
                {"max_weight_kg": t.max_weight_kg,
                 "price_usd": t.price_usd}
                for t in self.tiers
            ],
        }


@dataclass
class Package:
    weight_kg: float
    destination_zone: str
    required_sla: SLA = "ground"
    residential: bool = False
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0

    @property
    def volume_l(self) -> float:
        return (
            max(0.0, self.length_cm)
            * max(0.0, self.width_cm)
            * max(0.0, self.height_cm)
            / 1000.0
        )


@dataclass
class Quote:
    carrier: str
    sla: SLA
    billable_weight_kg: float
    base_price_usd: float
    surcharges_usd: float
    total_usd: float
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "carrier": self.carrier,
            "sla": self.sla,
            "billable_weight_kg": round(self.billable_weight_kg, 3),
            "base_price_usd": round(self.base_price_usd, 2),
            "surcharges_usd": round(self.surcharges_usd, 2),
            "total_usd": round(self.total_usd, 2),
            "reason": self.reason,
        }


@dataclass
class QuoteResult:
    best: Quote | None
    options: list[Quote] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.as_dict() if self.best else None,
            "options": [o.as_dict() for o in self.options],
            "rejected": self.rejected,
        }


# ── SLA helpers ────────────────────────────────────────────

_SLA_RANK = {"overnight": 0, "two_day": 1, "ground": 2}


def _sla_meets(carrier_sla: SLA, required: SLA) -> bool:
    """True iff the carrier's SLA is AT LEAST as fast as required."""
    return _SLA_RANK.get(carrier_sla, 99) <= _SLA_RANK.get(required, 99)


# ── Optimizer ──────────────────────────────────────────────

class ShippingOptimizer:
    def __init__(self) -> None:
        self._carriers: list[Carrier] = []

    def add_carrier(self, carrier: Carrier) -> None:
        if not carrier.name:
            raise ValueError("carrier name required")
        if not carrier.tiers:
            raise ValueError("carrier needs at least one rate tier")
        carrier.tiers = sorted(
            carrier.tiers, key=lambda t: t.max_weight_kg,
        )
        self._carriers = [
            c for c in self._carriers if c.name != carrier.name
        ] + [carrier]

    def add_many(self, carriers: Iterable[Carrier]) -> None:
        for c in carriers:
            self.add_carrier(c)

    def carriers(self) -> list[Carrier]:
        return list(self._carriers)

    # ── Quoting ────────────────────────────────────────────

    def quote(
        self, carrier: Carrier, package: Package,
    ) -> Quote | tuple[str, str]:
        if package.destination_zone not in carrier.zones:
            return (carrier.name,
                     f"zone {package.destination_zone!r} not covered")
        if not _sla_meets(carrier.sla, package.required_sla):
            return (carrier.name,
                     f"sla {carrier.sla} slower than "
                     f"{package.required_sla}")
        billable = float(package.weight_kg)
        if carrier.dim_weight_divisor > 0 and package.volume_l > 0:
            dim_weight = package.volume_l / carrier.dim_weight_divisor
            billable = max(billable, dim_weight)
        tier = next(
            (t for t in carrier.tiers
              if billable <= t.max_weight_kg),
            None,
        )
        if tier is None:
            return (carrier.name,
                     f"over-weight ({billable:.2f}kg)")
        base = tier.price_usd
        surcharges = 0.0
        if carrier.fuel_surcharge_pct > 0:
            surcharges += base * carrier.fuel_surcharge_pct
        if package.residential and carrier.residential_fee_usd > 0:
            surcharges += carrier.residential_fee_usd
        total = base + surcharges
        return Quote(
            carrier=carrier.name,
            sla=carrier.sla,
            billable_weight_kg=billable,
            base_price_usd=base,
            surcharges_usd=surcharges,
            total_usd=total,
            reason=(f"tier ≤ {tier.max_weight_kg}kg, "
                    f"billable {billable:.2f}kg"),
        )

    def all_options(self, package: Package) -> QuoteResult:
        result = QuoteResult(best=None)
        for c in self._carriers:
            out = self.quote(c, package)
            if isinstance(out, Quote):
                result.options.append(out)
            else:
                result.rejected.append(out)
        result.options.sort(key=lambda q: q.total_usd)
        result.best = result.options[0] if result.options else None
        return result

    def best_option(self, package: Package) -> Quote | None:
        return self.all_options(package).best

    def cheapest_per_carrier(
        self, package: Package,
    ) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for c in self._carriers:
            q = self.quote(c, package)
            if isinstance(q, Quote):
                out[c.name] = q
        return out
