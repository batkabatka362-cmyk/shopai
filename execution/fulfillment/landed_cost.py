"""Landed-cost calculator with de-minimis / tariff awareness.

Wave F-1 of IMPLEMENTATION_PLAN_2026. The single highest-leverage
vendor-independent lever for dropshippers in 2026 is the landed-
cost calculation: FOB + duty + tax + shipping + fulfillment fee
+ payment processing → true cost per unit.

Critical 2026 variable: **US Section 321 "de minimis"**. The
$800 duty-free threshold for China-origin goods was suspended
Feb 2025, temporarily reinstated pending CBP readiness, and
remains volatile. A flip either way adds or removes ~15-30%
landed cost overnight.

The module is a **pure function** so `rl_pricing`,
`campaign_activator`, and `launch_simulator` can call it
hundreds of times per decision cycle without side-effects.

Supported origin / destination pairs:
  * CN → US
  * CN → EU
  * CN → UK
  * US → US
  * EU → EU
  * US → EU / UK (reverse cross-border)

Each pair has a **tariff regime** (callable) that returns duty
as a fraction of FOB. De-minimis thresholds are applied first:
under-threshold shipments pay no duty. The current US de-minimis
state is controlled by ``SHOPAI_US_DE_MINIMIS_STATUS`` env var:

  * ``active``           — $800 threshold applies for all origins
  * ``suspended_cn``     — $800 threshold does NOT apply to
                           CN-origin goods (default 2026-04
                           per CBP status)
  * ``suspended_all``    — $800 threshold fully removed
  * ``custom:<usd>``     — owner overrides to a specific cap

Deterministic, LLM-free. No I/O, no persistence. Tests run
offline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("execution.fulfillment.landed_cost")


_DEFAULT_DE_MINIMIS_USD: dict[str, float] = {
    "US": 800.0,
    "EU": 150.0,      # EU IOSS VAT-exempt threshold removed
                      # July 2021; retained as historical ref
                      # (practical value 0 post-IOSS).
    "UK": 135.0,      # UK VAT collected at point of sale
                      # above this; duty-free under it.
}

_US_DE_MINIMIS_ENV = "SHOPAI_US_DE_MINIMIS_STATUS"

_VALID_US_STATUSES = (
    "active", "suspended_cn", "suspended_all",
)


@dataclass
class LandedCostInput:
    fob_usd: float                 # supplier cost (CJ / Ali)
    destination: str               # "US" | "EU" | "UK"
    origin: str = "CN"
    hts_code: str = ""             # optional — drives tariff
    weight_g: float = 300.0
    shipping_usd: float = 0.0      # per-unit shipping
    payment_processing_pct: float = 0.029  # Shopify / Stripe
    fulfillment_fee_usd: float = 0.0
    vat_pct: float = 0.0           # override if known

    def __post_init__(self) -> None:
        if self.fob_usd < 0:
            raise ValueError("fob_usd must be ≥ 0")
        if not self.destination:
            raise ValueError("destination required")
        if self.weight_g < 0:
            raise ValueError("weight_g must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "fob_usd": round(self.fob_usd, 4),
            "destination": self.destination,
            "origin": self.origin,
            "hts_code": self.hts_code,
            "weight_g": self.weight_g,
            "shipping_usd": round(self.shipping_usd, 4),
            "payment_processing_pct": round(
                self.payment_processing_pct, 4,
            ),
            "fulfillment_fee_usd": round(
                self.fulfillment_fee_usd, 4,
            ),
            "vat_pct": round(self.vat_pct, 4),
        }


@dataclass
class LandedCostBreakdown:
    fob_usd: float
    shipping_usd: float
    duty_usd: float
    vat_usd: float
    payment_processing_usd: float
    fulfillment_fee_usd: float
    total_usd: float
    de_minimis_applied: bool
    duty_rate: float
    vat_rate: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def margin_ratio_at(self) -> Callable[[float], float]:
        """Return a closure computing margin ratio given a
        retail price."""
        total = self.total_usd

        def _margin(retail_price_usd: float) -> float:
            if retail_price_usd <= 0:
                return 0.0
            return max(
                0.0,
                (retail_price_usd - total)
                / retail_price_usd,
            )
        return _margin

    def as_dict(self) -> dict[str, Any]:
        return {
            "fob_usd": round(self.fob_usd, 4),
            "shipping_usd": round(self.shipping_usd, 4),
            "duty_usd": round(self.duty_usd, 4),
            "vat_usd": round(self.vat_usd, 4),
            "payment_processing_usd": round(
                self.payment_processing_usd, 4,
            ),
            "fulfillment_fee_usd": round(
                self.fulfillment_fee_usd, 4,
            ),
            "total_usd": round(self.total_usd, 4),
            "de_minimis_applied": self.de_minimis_applied,
            "duty_rate": round(self.duty_rate, 4),
            "vat_rate": round(self.vat_rate, 4),
            "notes": list(self.notes),
        }


# ── Tariff tables ──────────────────────────────────────────

# Duty rate as fraction of FOB per (origin, destination, HTS
# category). Kept deliberately coarse — owner can override
# by passing exact HTS code later. These are mid-2026 US MFN
# averages for common dropship categories.
_DUTY_TABLE: dict[
    tuple[str, str], dict[str, float]
] = {
    ("CN", "US"): {
        "default": 0.075,   # weighted MFN + Section 301
        "apparel": 0.16,
        "electronics": 0.03,
        "home": 0.05,
    },
    ("CN", "EU"): {
        "default": 0.04,
        "apparel": 0.12,
        "electronics": 0.02,
    },
    ("CN", "UK"): {
        "default": 0.04,
        "apparel": 0.12,
        "electronics": 0.02,
    },
    ("US", "US"): {"default": 0.0},
    ("EU", "EU"): {"default": 0.0},
    ("UK", "UK"): {"default": 0.0},
    ("US", "EU"): {"default": 0.02},
    ("US", "UK"): {"default": 0.02},
}


_VAT_TABLE: dict[str, float] = {
    "US": 0.0,      # no federal VAT
    "EU": 0.20,     # blended EU average
    "UK": 0.20,
}


_HTS_TO_CATEGORY: dict[str, str] = {
    "6": "apparel",       # HTS 61/62xx textiles
    "8": "electronics",   # HTS 85xx electrical
    "9": "home",          # HTS 94xx furniture
}


def _categorize_hts(hts: str) -> str:
    """Map HTS code prefix to a duty-table category."""
    if not hts:
        return "default"
    prefix = hts.strip()[:1]
    return _HTS_TO_CATEGORY.get(prefix, "default")


# ── De-minimis logic ───────────────────────────────────────


def _effective_us_threshold(
    origin: str,
    override: str | None = None,
) -> float:
    """Return the effective US de-minimis threshold USD.

    0.0 means "no threshold, every shipment dutiable". The
    env var ``SHOPAI_US_DE_MINIMIS_STATUS`` (or explicit
    ``override``) drives this per 2026 US policy volatility.
    """
    status = (
        override
        if override is not None
        else os.environ.get(_US_DE_MINIMIS_ENV, "active")
    )
    status = (status or "active").lower().strip()
    if status.startswith("custom:"):
        try:
            return float(status.split(":", 1)[1])
        except (TypeError, ValueError):
            return _DEFAULT_DE_MINIMIS_USD["US"]
    if status == "suspended_all":
        return 0.0
    if status == "suspended_cn":
        return 0.0 if origin.upper() == "CN" else (
            _DEFAULT_DE_MINIMIS_USD["US"]
        )
    # active (default)
    return _DEFAULT_DE_MINIMIS_USD["US"]


def effective_de_minimis(
    *,
    origin: str,
    destination: str,
    status_override: str | None = None,
) -> float:
    """Return the effective de-minimis threshold for a
    (origin, destination) pair in USD."""
    dest = destination.upper()
    if dest == "US":
        return _effective_us_threshold(
            origin=origin, override=status_override,
        )
    return _DEFAULT_DE_MINIMIS_USD.get(dest, 0.0)


# ── Main calculator ───────────────────────────────────────


def calculate_landed_cost(
    cost_input: LandedCostInput,
    *,
    de_minimis_override: str | None = None,
) -> LandedCostBreakdown:
    """Pure function — given inputs, returns breakdown.

    Steps:
      1. Look up duty rate from table (fallback to default).
      2. Apply de-minimis — if FOB + shipping < threshold,
         set duty = 0.
      3. Compute VAT on (FOB + shipping + duty) for EU/UK,
         or use override.
      4. Add payment processing (% of retail ≈ % of FOB for
         margin math — owner pays this on revenue side, but
         we fold into cost for conservative margin floor).
      5. Add fulfillment fee.
    """
    if not isinstance(cost_input, LandedCostInput):
        raise TypeError(
            "cost_input must be LandedCostInput",
        )
    origin = cost_input.origin.upper()
    dest = cost_input.destination.upper()
    notes: list[str] = []

    # Duty
    cat = _categorize_hts(cost_input.hts_code)
    duty_map = _DUTY_TABLE.get(
        (origin, dest), {"default": 0.0},
    )
    duty_rate = duty_map.get(
        cat, duty_map.get("default", 0.0),
    )

    threshold = effective_de_minimis(
        origin=origin,
        destination=dest,
        status_override=de_minimis_override,
    )
    shipment_value = (
        cost_input.fob_usd + cost_input.shipping_usd
    )
    de_minimis_applied = False
    if threshold > 0 and shipment_value < threshold:
        duty_rate = 0.0
        de_minimis_applied = True
        notes.append(
            f"de-minimis applied (${threshold:.2f} "
            f"{dest} threshold)"
        )
    elif threshold <= 0 and dest == "US":
        notes.append(
            "US de-minimis suspended for this origin",
        )

    duty_usd = cost_input.fob_usd * duty_rate

    # VAT
    vat_rate = cost_input.vat_pct
    if vat_rate == 0.0:
        vat_rate = _VAT_TABLE.get(dest, 0.0)
    vat_base = (
        cost_input.fob_usd
        + cost_input.shipping_usd
        + duty_usd
    )
    vat_usd = vat_base * vat_rate

    # Payment processing (conservative: on cost side)
    payment_usd = (
        cost_input.fob_usd
        * cost_input.payment_processing_pct
    )

    total = (
        cost_input.fob_usd
        + cost_input.shipping_usd
        + duty_usd
        + vat_usd
        + payment_usd
        + cost_input.fulfillment_fee_usd
    )

    return LandedCostBreakdown(
        fob_usd=cost_input.fob_usd,
        shipping_usd=cost_input.shipping_usd,
        duty_usd=duty_usd,
        vat_usd=vat_usd,
        payment_processing_usd=payment_usd,
        fulfillment_fee_usd=cost_input.fulfillment_fee_usd,
        total_usd=total,
        de_minimis_applied=de_minimis_applied,
        duty_rate=duty_rate,
        vat_rate=vat_rate,
        notes=tuple(notes),
    )


# ── Convenience ─────────────────────────────────────────────


def minimum_retail_for_margin(
    cost_input: LandedCostInput,
    *,
    target_margin: float = 0.30,
    de_minimis_override: str | None = None,
) -> float:
    """Compute the retail price needed to hit ``target_margin``
    given the landed cost. margin = (retail - total) / retail
    → retail = total / (1 - margin)."""
    if not 0.0 <= target_margin < 1.0:
        raise ValueError(
            "target_margin must be in [0, 1)",
        )
    breakdown = calculate_landed_cost(
        cost_input,
        de_minimis_override=de_minimis_override,
    )
    if target_margin == 0.0:
        return breakdown.total_usd
    return breakdown.total_usd / (1.0 - target_margin)
