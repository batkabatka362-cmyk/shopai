"""Payload discoverer substrate (Wave 820).

Phase 37 surfaced that 7 of 10 autonomy domains are
"substrate-only" -- the applier exists, but no engine wraps
it, so cycle never invokes it. Phase 38 added a manual
``shopai autonomy-fire`` CLI that takes operator-supplied
payloads.

This module is the missing bridge: per-domain DISCOVERERS
that generate payloads automatically by reading the relevant
Shopify resource (orders / products / customers) and
filtering for the domain's signal class. Once registered,
the cycle controller (Wave 822+) can call discoverer ->
applier for any armed substrate-mode domain.

Default: every substrate-mode domain has NO discoverer
registered, so cycle still no-ops. Each per-domain wave
(W821 shipping_alert, W824 catalog_quality, W825
order_followup, ...) registers one discoverer at a time.

The discoverer contract: a zero-arg callable returning
``DiscoveryResult(domain, payload, source, discovered_at,
error)``. ``payload`` is a ``list[dict]`` matching the
target applier's expected row shape.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class DiscoveryResult:
    domain: str
    payload: list[dict] = field(default_factory=list)
    source: str = ""
    discovered_at: float = field(default_factory=time.time)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def payload_size(self) -> int:
        return len(self.payload)


# Per-domain discoverer registry. Each domain (from
# autonomy_armed.DOMAIN_APPLY_FLAGS) may register at most one
# discoverer. Substrate-mode domains without a discoverer
# simply don't auto-fire; engine-mode domains don't need a
# discoverer (engine flow.py emits the apply_X payload).
_DISCOVERERS: dict[str, Callable[[], DiscoveryResult]] = {}


def register_discoverer(
    domain: str,
    fn: Callable[[], DiscoveryResult],
) -> None:
    """Register a discoverer for the given domain. Idempotent
    re-register replaces. Raises on unknown domain to catch
    typos at import time."""
    try:
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS,
        )
    except Exception:
        DOMAIN_APPLY_FLAGS = {}
    if DOMAIN_APPLY_FLAGS and domain not in DOMAIN_APPLY_FLAGS:
        raise ValueError(
            f"unknown autonomy domain {domain!r}; known: "
            f"{', '.join(sorted(DOMAIN_APPLY_FLAGS))}"
        )
    _DISCOVERERS[domain] = fn


def unregister_discoverer(domain: str) -> bool:
    """Remove the discoverer. Returns True if one existed."""
    return _DISCOVERERS.pop(domain, None) is not None


def has_discoverer(domain: str) -> bool:
    return domain in _DISCOVERERS


def registered_domains() -> list[str]:
    return sorted(_DISCOVERERS)


def discover(domain: str) -> DiscoveryResult:
    """Run the registered discoverer for ``domain``. Returns a
    ``DiscoveryResult`` with payload, source, timing, and
    optional error. Never raises."""
    now = time.time()
    fn = _DISCOVERERS.get(domain)
    if fn is None:
        return DiscoveryResult(
            domain=domain,
            payload=[],
            source="",
            discovered_at=now,
            error=f"no discoverer registered for {domain!r}",
        )
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discoverer for %s raised: %s", domain, exc,
        )
        return DiscoveryResult(
            domain=domain,
            payload=[],
            source="",
            discovered_at=now,
            error=f"discoverer raised: {exc!s:.200}",
        )
    if not isinstance(result, DiscoveryResult):
        return DiscoveryResult(
            domain=domain,
            payload=[],
            source="",
            discovered_at=now,
            error=(
                f"discoverer returned non-DiscoveryResult "
                f"({type(result).__name__})"
            ),
        )
    # Validate payload shape -- a list of dicts. Per
    # autonomy_fire contract.
    if not isinstance(result.payload, list):
        return DiscoveryResult(
            domain=domain,
            payload=[],
            source=result.source,
            discovered_at=now,
            error=(
                f"discoverer payload must be list, got "
                f"{type(result.payload).__name__}"
            ),
        )
    for i, row in enumerate(result.payload):
        if not isinstance(row, dict):
            return DiscoveryResult(
                domain=domain,
                payload=[],
                source=result.source,
                discovered_at=now,
                error=(
                    f"discoverer payload[{i}] must be dict, "
                    f"got {type(row).__name__}"
                ),
            )
    return result


def discover_all_armed_substrate() -> list[DiscoveryResult]:
    """Discover payloads for every CURRENTLY-armed substrate-
    mode domain that has a registered discoverer. Used by the
    cycle controller (W822+)."""
    out: list[DiscoveryResult] = []
    try:
        from core.automation.autonomy_armed import (
            DOMAIN_FIRING_MODE, list_armed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discover_all: armed import raised: %s", exc,
        )
        return out
    for entry in list_armed():
        if DOMAIN_FIRING_MODE.get(entry.domain) != "substrate":
            continue
        if not has_discoverer(entry.domain):
            continue
        out.append(discover(entry.domain))
    return out
