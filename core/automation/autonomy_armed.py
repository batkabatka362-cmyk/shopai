"""Autonomy arm-state substrate (Wave 811 + W815).

Bridges the gap between "autonomy domain X has substrate" and
"autonomy domain X actually fires in the cycle."

Two firing modes:

  * ``engine`` -- a registered engine (in the writeback audit's
    wired_map) consumes the apply_X flag from its input. The
    cycle controller already injects apply_X=True for every
    wired+selected member (see cli.py _cmd_cycle_run, line
    ~22189). When the domain is armed, the operator gets
    surface-level confirmation that the engine WILL fire.

  * ``substrate`` -- no engine wraps the applier. The autonomy
    domain has a standalone apply_X function exposed via
    ``engines.<domain>_autonomy.<X>_applier``. The cycle does
    NOT call these today; the appliers are exercised only by
    autonomy-smoke. Arming a substrate-only domain is
    aspirational -- the operator's intent is recorded, but no
    cycle integration fires it yet.

Default state is DISARMED for every domain. Arming requires an
explicit operator action (CLI flag) so the substrate stays
safe-by-default.

Pattern J guard: writes short-circuit under pytest so test runs
don't pollute ``data/autonomy_armed.json``.
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


# (domain -> list of apply_X flags) -- catalog of every flag
# the domain's substrate exposes. For ``engine``-mode domains
# the flags appear in the wired_map (engine flow.py reads them);
# for ``substrate``-mode domains the flags are documented for
# future cycle integration but no engine reads them today.
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


# Honest per-domain firing-mode declaration. ``engine`` means an
# engine in the writeback audit's wired_map consumes the flag --
# cycle will inject apply_X=True today and fire. ``substrate``
# means the applier is standalone -- cycle does NOT call it; the
# arm is aspirational until cycle wiring lands.
DOMAIN_FIRING_MODE: dict[str, str] = {
    "customer_support": "engine",   # returns_management + cs
    "marketing": "engine",          # roas_guardrails
    "fulfillment": "substrate",
    "inventory": "substrate",
    "discount_cleanup": "substrate",
    "order_followup": "substrate",
    "product_seo": "substrate",
    "customer_outreach": "substrate",
    "catalog_quality": "substrate",
    "shipping_alert": "substrate",
}


def firing_mode_for_domain(domain: str) -> str:
    """``engine`` or ``substrate``. Unknown domain -> ``unknown``."""
    return DOMAIN_FIRING_MODE.get(domain, "unknown")


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


class ArmCooldownError(RuntimeError):
    """Raised by ``arm`` when ``force=False`` and the domain
    was auto-disarmed within the cooldown window."""

    def __init__(
        self,
        domain: str,
        hours_remaining: float,
    ) -> None:
        super().__init__(
            f"{domain!r} was auto-disarmed recently; "
            f"cooldown {hours_remaining:.1f}h remaining. "
            "Pass force=True (CLI: --force) to override."
        )
        self.domain = domain
        self.hours_remaining = hours_remaining


def _cooldown_hours() -> float:
    raw = os.environ.get(
        "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS", "12.0",
    )
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 12.0


def arm(
    domain: str,
    reason: str = "",
    *,
    force: bool = False,
) -> ArmedEntry:
    """Arm the given domain. Idempotent.

    Returns the resulting entry (existing if already armed, else
    a freshly-created one). Raises ValueError on unknown domain.

    W859: when ``force=False`` (default), refuses to arm a
    domain that was auto-disarmed within the last
    ``SHOPAI_AUTO_DISARM_COOLDOWN_HOURS`` (default 12) hours.
    Raises ``ArmCooldownError`` with the remaining cooldown.
    ``force=True`` bypasses the check (operator override).
    """
    if domain not in DOMAIN_APPLY_FLAGS:
        raise ValueError(
            f"unknown autonomy domain: {domain!r} "
            f"(known: {sorted(DOMAIN_APPLY_FLAGS)})"
        )
    if not force:
        try:
            from core.automation.substrate_fire_disarm_log import (  # noqa
                last_disarm_at,
            )
            last = last_disarm_at(domain)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "arm: disarm-log check raised: %s", exc,
            )
            last = None
        if last is not None:
            cooldown = _cooldown_hours()
            elapsed = (time.time() - last) / 3600.0
            if elapsed < cooldown:
                raise ArmCooldownError(
                    domain=domain,
                    hours_remaining=cooldown - elapsed,
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
