"""Autonomy arm-state substrate (Wave 811).

Bridges the gap between "autonomy domain X has substrate" and
"autonomy domain X actually fires in the cycle." Each of the 10
autonomy domains gates its applier behind ``data.apply_X=True``
in its engine input -- but the cycle controller has historically
never set those flags. Result: substrate is built, audits pass,
operator sees ``applied=0`` for every domain.

This module is the operator-facing arm/disarm switch. Once a
domain is armed, the cycle controller (separate wave) injects
the corresponding ``apply_X=True`` into the engine's input when
the engine fires.

Default state is DISARMED for every domain. Arming requires an
explicit operator action (env-var unlock or CLI flag) so the
substrate stays safe-by-default.

Pattern J guard: writes short-circuit under pytest so test runs
don't pollute ``data/autonomy_armed.json``.

The (domain -> apply-flag) catalog lives here too so the cycle
controller has one source of truth.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = Path("data") / "autonomy_armed.json"


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


# (domain -> list of apply_X flags) -- each domain's engine flow
# reads these from its input data dict. Multiple flags per domain
# when one logical domain wraps multiple appliers (e.g. customer
# support has refund + ticket-tag).
DOMAIN_APPLY_FLAGS: dict[str, tuple[str, ...]] = {
    "customer_support": (
        "apply_refunds",
        "apply_ticket_tags",
    ),
    "marketing": ("apply_budget_changes",),
    "fulfillment": ("apply_fulfillment_routes",),
    "inventory": ("apply_inventory_reorders",),
    "discount_cleanup": ("apply_discount_cleanup",),
    "order_followup": ("apply_order_followup",),
    "product_seo": ("apply_product_seo",),
    "customer_outreach": ("apply_customer_outreach",),
    "catalog_quality": ("apply_catalog_quality",),
    "shipping_alert": ("apply_shipping_alert",),
}


@dataclass
class ArmedEntry:
    domain: str
    armed_at: float
    reason: str = ""


@dataclass
class ArmedState:
    entries: list[ArmedEntry] = field(default_factory=list)

    def is_armed(self, domain: str) -> bool:
        return any(e.domain == domain for e in self.entries)

    def get(self, domain: str) -> ArmedEntry | None:
        for e in self.entries:
            if e.domain == domain:
                return e
        return None


def _load_state() -> ArmedState:
    if not _STATE_PATH.exists():
        return ArmedState()
    try:
        raw = json.loads(
            _STATE_PATH.read_text(encoding="utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("autonomy_armed: load raised: %s", exc)
        return ArmedState()
    entries = [
        ArmedEntry(
            domain=e["domain"],
            armed_at=float(e.get("armed_at", 0.0)),
            reason=e.get("reason", ""),
        )
        for e in raw.get("entries", [])
        if isinstance(e, dict) and "domain" in e
    ]
    return ArmedState(entries=entries)


def _save_state(state: ArmedState) -> None:
    if _is_test_environment():
        return
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(
            {"entries": [asdict(e) for e in state.entries]},
            indent=2,
        ),
        encoding="utf-8",
    )


def is_armed(domain: str) -> bool:
    """True iff the given domain is currently armed."""
    return _load_state().is_armed(domain)


def list_armed() -> list[ArmedEntry]:
    """All currently-armed domain entries in stable order."""
    return list(_load_state().entries)


def arm(domain: str, reason: str = "") -> ArmedEntry:
    """Arm the given domain. Idempotent.

    Returns the resulting entry (existing if already armed, else
    a freshly-created one). Raises ValueError on unknown domain.
    """
    if domain not in DOMAIN_APPLY_FLAGS:
        raise ValueError(
            f"unknown autonomy domain: {domain!r} "
            f"(known: {sorted(DOMAIN_APPLY_FLAGS)})"
        )
    state = _load_state()
    existing = state.get(domain)
    if existing is not None:
        return existing
    entry = ArmedEntry(
        domain=domain,
        armed_at=time.time(),
        reason=reason,
    )
    state.entries.append(entry)
    _save_state(state)
    return entry


def disarm(domain: str) -> bool:
    """Disarm the given domain. Idempotent.

    Returns True if a previously-armed entry was removed, False if
    the domain wasn't armed.
    """
    state = _load_state()
    if not state.is_armed(domain):
        return False
    state.entries = [
        e for e in state.entries if e.domain != domain
    ]
    _save_state(state)
    return True


def disarm_all() -> int:
    """Emergency disarm -- remove every armed entry. Returns the
    count of entries removed."""
    state = _load_state()
    count = len(state.entries)
    if count == 0:
        return 0
    state.entries = []
    _save_state(state)
    return count


def apply_flags_for_domain(domain: str) -> tuple[str, ...]:
    """The (apply_X, ...) flags an armed domain should inject."""
    return DOMAIN_APPLY_FLAGS.get(domain, ())
