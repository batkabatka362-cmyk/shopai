"""Substrate-domain cycle-fire bridge (Wave 822).

Connects the autonomy_armed flag (W815) -> discoverer
(W820+W821+) -> applier (W816) chain. Called from
``_cmd_cycle_run`` post-cycle so that armed substrate-mode
domains automatically fire their appliers with
discoverer-generated payloads.

Safety: requires ``SHOPAI_AUTONOMY_FIRE_CONFIRM=1`` env (sibling
to SHOPAI_CYCLE_RUN_CONFIRM). Without the env, runs in dry-run
mode -- discovers payloads + logs counts but never invokes the
applier. Pattern J guard for tests.

For each armed substrate-mode domain with a registered
discoverer:
  1. Run the discoverer
  2. If payload non-empty, invoke the applier via autonomy_fire
  3. Capture the result in a SubstrateFireReport

Engine-mode domains are skipped (cycle's existing wired_map
already fires them). Substrate-mode without a discoverer is
skipped (logged for visibility).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CONFIRM_ENV = "SHOPAI_AUTONOMY_FIRE_CONFIRM"


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class SubstrateFireOutcome:
    domain: str
    discovered: int = 0
    invoked: bool = False
    events: int = 0
    duration_ms: float = 0.0
    reason: str = ""  # e.g. "fired", "no_discoverer", "dry_run"
    error: str = ""
    store_id: str | None = None  # W837 per-store scope


@dataclass
class SubstrateFireReport:
    outcomes: list[SubstrateFireOutcome] = field(
        default_factory=list,
    )
    confirm_set: bool = False
    test_skip: bool = False
    store_id: str | None = None  # W837 per-store scope

    @property
    def total_invoked(self) -> int:
        return sum(1 for o in self.outcomes if o.invoked)

    @property
    def total_discovered_rows(self) -> int:
        return sum(o.discovered for o in self.outcomes)


def fire_armed_substrate_domains(
    *,
    store_id: str | None = None,
) -> SubstrateFireReport:
    """Iterate armed substrate-mode domains + run discoverer
    -> applier chain. Returns a report; never raises.

    W837: when ``store_id`` is supplied, discoverers are
    invoked scoped to that store + outcomes carry the
    store_id for downstream attribution.
    """
    report = SubstrateFireReport()
    report.store_id = store_id
    if _is_test_environment():
        report.test_skip = True
        return report

    report.confirm_set = bool(
        os.environ.get(_CONFIRM_ENV),
    )

    try:
        from core.automation import (  # noqa: F401
            discoverer_registry,
        )
        from core.automation.autonomy_armed import (
            DOMAIN_FIRING_MODE, list_armed,
        )
        from core.automation.autonomy_fire import fire
        from core.automation.payload_discoverer import (
            discover, has_discoverer,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "substrate_fire import raised: %s", exc,
        )
        return report

    for entry in list_armed():
        domain = entry.domain
        if DOMAIN_FIRING_MODE.get(domain) != "substrate":
            continue
        outcome = SubstrateFireOutcome(
            domain=domain, store_id=store_id,
        )
        if not has_discoverer(domain):
            outcome.reason = "no_discoverer"
            report.outcomes.append(outcome)
            continue
        disc = discover(domain, store_id=store_id)
        if not disc.ok:
            outcome.reason = "discoverer_error"
            outcome.error = disc.error
            report.outcomes.append(outcome)
            continue
        outcome.discovered = disc.payload_size
        if disc.payload_size == 0:
            outcome.reason = "empty_payload"
            report.outcomes.append(outcome)
            continue
        if not report.confirm_set:
            outcome.reason = "dry_run"
            report.outcomes.append(outcome)
            continue
        # Live invocation
        fr = fire(domain, disc.payload, dry_run=False)
        outcome.invoked = fr.invoked
        outcome.events = len(fr.events) if fr.events else 0
        outcome.duration_ms = fr.duration_ms
        if fr.error:
            outcome.error = fr.error
            outcome.reason = "applier_error"
        else:
            outcome.reason = "fired"
        report.outcomes.append(outcome)

    return report
