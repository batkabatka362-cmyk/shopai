"""Pattern BL audit: legacy env alias inventory (W889).

Surfaces the per-discoverer ``legacy_env`` aliases that survive
after the W888 standardisation. Pattern BL is INFORMATIONAL --
it never fails. Its purpose is to give operators a single
view of "which legacy env names still resolve" so they can
plan migration to the standard naming convention.

The catalog below mirrors the resolve_int/float
``legacy_env=`` calls in W888. New non-standard knobs added
later should be entered here too so Pattern BL stays
authoritative.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# (discoverer module, knob, standard env name, legacy env name)
_LEGACY_CATALOG: list[tuple[str, str, str, str]] = [
    (
        "customer_outreach",
        "VIP_USD",
        "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_VIP_USD",
        "SHOPAI_CUSTOMER_OUTREACH_VIP_USD",
    ),
    (
        "discount_cleanup",
        "MIN_AGE_DAYS",
        "SHOPAI_DISCOUNT_CLEANUP_DISCOVER_MIN_AGE_DAYS",
        "SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS",
    ),
    (
        "fulfillment",
        "DEFAULT_LOCATION_ID",
        (
            "SHOPAI_FULFILLMENT_DISCOVER_DEFAULT_"
            "LOCATION_ID"
        ),
        "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID",
    ),
    (
        "inventory",
        "SAFETY_STOCK",
        "SHOPAI_INVENTORY_DISCOVER_SAFETY_STOCK",
        "SHOPAI_INVENTORY_SAFETY_STOCK",
    ),
    (
        "inventory",
        "REORDER_MULTIPLIER",
        "SHOPAI_INVENTORY_DISCOVER_REORDER_MULTIPLIER",
        "SHOPAI_INVENTORY_REORDER_MULTIPLIER",
    ),
]


@dataclass
class LegacyAlias:
    discoverer: str
    knob: str
    standard_env: str
    legacy_env: str
    standard_set: bool = False
    legacy_set: bool = False


@dataclass
class PatternBLReport:
    aliases: list[LegacyAlias] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        # Informational audit: never fails.
        return False

    @property
    def legacy_only_count(self) -> int:
        return sum(
            1 for a in self.aliases
            if a.legacy_set and not a.standard_set
        )

    @property
    def both_set_count(self) -> int:
        """Aliases where BOTH standard + legacy are set.
        Standard wins per the W887 lookup order, but the
        legacy var is redundant -- operator should remove."""
        return sum(
            1 for a in self.aliases
            if a.standard_set and a.legacy_set
        )

    @property
    def migrated_count(self) -> int:
        return sum(
            1 for a in self.aliases
            if a.standard_set and not a.legacy_set
        )


def _is_set(name: str) -> bool:
    v = os.environ.get(name, "")
    return bool(v) and v != ""


def run_pattern_bl_audit() -> PatternBLReport:
    """Walk the legacy catalog + report each alias' env state."""
    report = PatternBLReport()
    for discoverer, knob, std, legacy in _LEGACY_CATALOG:
        report.aliases.append(LegacyAlias(
            discoverer=discoverer,
            knob=knob,
            standard_env=std,
            legacy_env=legacy,
            standard_set=_is_set(std),
            legacy_set=_is_set(legacy),
        ))
    return report
