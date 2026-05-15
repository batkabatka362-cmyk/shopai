"""Capability coverage audit — every Shopify Capability enum
value should be claimed by at least one registered adapter.

The companion to ``core.approval.coverage_audit`` (Pattern K —
dispatchers covering engine enqueue calls). This module
implements Pattern Y: every ``Capability.SHOPIFY_*`` enum value
should be claimed by ≥1 adapter's ``capabilities`` set.

When a new ``SHOPIFY_*`` capability lands on the enum without a
matching adapter, engines that route to it via
``router.execute(Capability.SHOPIFY_X, ...)`` will fail with
``AdapterNotConfigured``. The failure is loud enough at the
single engine, but silent at the system level — nothing
proactively surfaces "this enum value is dead-ended". Pattern Y
makes that an explicit gate.

Two flavours of issue caught:

  1. **Unclaimed capability**: enum has ``SHOPIFY_X``, but no
     adapter declares it. Engines calling for it hit
     ``AdapterNotConfigured``.

  2. **Orphan capability** (defensive): adapter declares a
     capability that doesn't exist on the enum. Symptom would
     be ``AttributeError`` at module load — usually caught by
     the test suite, but the audit codifies the check.

Both are surfaced by :func:`audit_capability_coverage`.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.adapters.base import Capability


@dataclass(frozen=True)
class CapabilityCoverageReport:
    """Result of the Pattern Y audit."""

    total_shopify_capabilities: int
    claimed_count: int
    unclaimed: list[str]
    orphan_claims: list[str]
    multi_claimed: dict[str, list[str]]
    has_gaps: bool


def audit_capability_coverage(
    adapter_classes: tuple | None = None,
) -> CapabilityCoverageReport:
    """Cross-reference every ``Capability.SHOPIFY_*`` enum value
    against the registered adapters.

    Args:
        adapter_classes: Optional tuple to scope the audit. Tests
            inject a subset. Production callers leave as None —
            the function reads the bootstrap tuple lazily so
            test patches land.

    Returns:
        :class:`CapabilityCoverageReport` with:
          * ``total_shopify_capabilities``: enum values starting
            with ``SHOPIFY_``
          * ``claimed_count``: enum values claimed by ≥1 adapter
          * ``unclaimed``: enum values claimed by 0 adapters
          * ``orphan_claims``: capability names some adapter
            declares but that don't exist on the enum (typo
            trap — should be empty)
          * ``multi_claimed``: capability → [adapter names] for
            values claimed by 2+ adapters (warning, not error —
            it can be legitimate but is worth surfacing)
          * ``has_gaps``: True iff ``unclaimed`` or
            ``orphan_claims`` is non-empty (CI gate uses this)
    """
    if adapter_classes is None:
        from core.adapters.shopify.bootstrap import (
            _SHOPIFY_ADAPTER_CLASSES as _CURRENT_CLASSES,
        )
        adapter_classes = _CURRENT_CLASSES

    all_shopify = {
        cap for cap in Capability if cap.name.startswith("SHOPIFY_")
    }
    claims: dict[Capability, list[str]] = {}
    orphan_claims: set[str] = set()

    for cls in adapter_classes:
        adapter_name = getattr(cls, "name", "") or cls.__name__
        for cap in getattr(cls, "capabilities", set()):
            # Defensive: a capability set might contain a stale
            # string (typo / not-yet-enum). Skip non-Capability
            # entries with a separate orphan-style report.
            if not isinstance(cap, Capability):
                orphan_claims.add(str(cap))
                continue
            claims.setdefault(cap, []).append(adapter_name)

    # Unclaimed = enum entries no adapter claimed
    unclaimed = sorted(
        cap.name for cap in all_shopify if cap not in claims
    )

    # Multi-claimed = enum entries claimed by 2+ adapters
    multi_claimed = {
        cap.name: sorted(adapters)
        for cap, adapters in claims.items()
        if len(adapters) > 1
    }

    return CapabilityCoverageReport(
        total_shopify_capabilities=len(all_shopify),
        claimed_count=sum(
            1 for cap in all_shopify if cap in claims
        ),
        unclaimed=unclaimed,
        orphan_claims=sorted(orphan_claims),
        multi_claimed=multi_claimed,
        has_gaps=bool(unclaimed or orphan_claims),
    )
