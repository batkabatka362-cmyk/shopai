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
    # W869: per-store scope. Empty string = fleet-wide (the
    # original W815 behaviour). Non-empty = scoped to one store.
    store_id: str = ""


@dataclass
class ArmedState:
    entries: list[ArmedEntry] = field(default_factory=list)

    def is_armed(
        self, domain: str, store_id: str = "",
    ) -> bool:
        """Match exact (domain, store_id) tuple. Empty
        store_id matches only the fleet-wide entry."""
        sid = store_id or ""
        for e in self.entries:
            if e.domain == domain and (e.store_id or "") == sid:
                return True
        return False

    def get(
        self, domain: str, store_id: str = "",
    ) -> ArmedEntry | None:
        sid = store_id or ""
        for e in self.entries:
            if e.domain == domain and (e.store_id or "") == sid:
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
            # W869: backward-compat -- pre-W869 entries lack
            # store_id; default to fleet-wide empty string.
            store_id=str(e.get("store_id", "") or ""),
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


def is_armed(domain: str, store_id: str = "") -> bool:
    """True iff the (domain, store_id) tuple is currently
    armed. Empty store_id checks the fleet-wide entry only."""
    return _load_state().is_armed(domain, store_id)


def list_armed(
    *,
    store_id: str | None = None,
) -> list[ArmedEntry]:
    """All currently-armed entries in stable order.

    W869: when ``store_id`` is supplied, returns only entries
    scoped to that store (exact match). When omitted, returns
    every entry (fleet-wide + per-store) so legacy callers see
    everything."""
    entries = list(_load_state().entries)
    if store_id is None:
        return entries
    sid = store_id or ""
    return [e for e in entries if (e.store_id or "") == sid]


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


def _cooldown_hours(domain: str | None = None) -> float:
    """Return cooldown hours for ``domain``. Per-domain env
    knob (``SHOPAI_AUTO_DISARM_COOLDOWN_<DOMAIN>_HOURS``)
    wins when set; else the global default applies."""
    if domain:
        per_domain = os.environ.get(
            f"SHOPAI_AUTO_DISARM_COOLDOWN_"
            f"{domain.upper()}_HOURS",
            "",
        )
        if per_domain:
            try:
                return max(0.0, float(per_domain))
            except (TypeError, ValueError):
                pass
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
    store_id: str = "",
) -> ArmedEntry:
    """Arm the (domain, store_id) tuple. Idempotent.

    Returns the resulting entry (existing if already armed, else
    a freshly-created one). Raises ValueError on unknown domain.

    W859: when ``force=False`` (default), refuses to arm a
    domain that was auto-disarmed within the last
    ``SHOPAI_AUTO_DISARM_COOLDOWN_HOURS`` (default 12) hours.
    Raises ``ArmCooldownError`` with the remaining cooldown.
    ``force=True`` bypasses the check (operator override).

    W869: ``store_id`` scopes the entry. Empty string (default)
    is fleet-wide -- back-compat with W815 callers. Non-empty
    arms the domain ONLY for that store. The cooldown check is
    keyed off ``(domain, store_id)`` so per-store cooldowns are
    independent.
    """
    if domain not in DOMAIN_APPLY_FLAGS:
        raise ValueError(
            f"unknown autonomy domain: {domain!r} "
            f"(known: {sorted(DOMAIN_APPLY_FLAGS)})"
        )
    sid = store_id or ""
    if not force:
        try:
            from core.automation.substrate_fire_disarm_log import (  # noqa
                last_disarm_at,
            )
            # W876: per-store arm queries per-store cooldown.
            # Fleet-wide arm (sid="") passes None to match the
            # W858 behaviour where any-scope disarm blocks
            # fleet re-arm.
            last = last_disarm_at(
                domain,
                store_id=sid if sid else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "arm: disarm-log check raised: %s", exc,
            )
            last = None
        if last is not None:
            cooldown = _cooldown_hours(domain)
            elapsed = (time.time() - last) / 3600.0
            if elapsed < cooldown:
                raise ArmCooldownError(
                    domain=domain,
                    hours_remaining=cooldown - elapsed,
                )
    state = _load_state()
    existing = state.get(domain, sid)
    if existing is not None:
        return existing
    entry = ArmedEntry(
        domain=domain,
        armed_at=time.time(),
        reason=reason,
        store_id=sid,
    )
    state.entries.append(entry)
    _save_state(state)
    return entry


def disarm(domain: str, store_id: str = "") -> bool:
    """Disarm the (domain, store_id) tuple. Idempotent.

    Returns True if a previously-armed entry was removed,
    False if the (domain, store_id) tuple wasn't armed.

    W869: empty ``store_id`` removes the fleet-wide entry
    only. Per-store entries for the same domain stay armed.
    To remove EVERY entry for a domain (fleet + per-store),
    call ``disarm_domain_all(domain)``.
    """
    sid = store_id or ""
    state = _load_state()
    if not state.is_armed(domain, sid):
        return False
    state.entries = [
        e for e in state.entries
        if not (
            e.domain == domain
            and (e.store_id or "") == sid
        )
    ]
    _save_state(state)
    return True


def disarm_domain_all(domain: str) -> int:
    """Remove every armed entry for ``domain`` regardless of
    store_id. Returns the count of entries removed."""
    state = _load_state()
    before = len(state.entries)
    state.entries = [
        e for e in state.entries if e.domain != domain
    ]
    removed = before - len(state.entries)
    if removed > 0:
        _save_state(state)
    return removed


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
