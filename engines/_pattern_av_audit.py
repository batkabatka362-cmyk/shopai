"""Pattern AV audit: payload-discoverer ownership parity (W823).

Phase 42-44 shipped the discoverer registry + cycle bridge.
Pattern AV is the standing audit that catches two drift classes:

  1. **Registered for unknown domain** -- discoverer keyed on
     a name that isn't in ``DOMAIN_APPLY_FLAGS``. Catches typos
     during per-domain wave (W824, W825, ...).

  2. **Registered for engine-mode domain** -- engine-mode
     domains don't need discoverers (their engine flow.py emits
     the apply_X payload). A discoverer for them is wasted code
     + a sign that someone misread the firing-mode catalog.

The audit is non-fatal for missing discoverers (substrate-mode
domains without discoverers are valid: cycle just no-ops them
with reason="no_discoverer"). The audit IS fatal for the two
drift classes above because each indicates a real wiring bug.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternAVViolation:
    domain: str
    reason: str


@dataclass
class PatternAVReport:
    registered_discoverers: list[str] = field(
        default_factory=list,
    )
    substrate_domains: list[str] = field(default_factory=list)
    engine_domains: list[str] = field(default_factory=list)
    substrate_without_discoverer: list[str] = field(
        default_factory=list,
    )
    clean_pairings: list[str] = field(default_factory=list)
    violations: list[PatternAVViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_av_audit() -> PatternAVReport:
    """Walk the discoverer registry + autonomy domain catalog,
    flag any (a) unknown-domain registration or (b) engine-mode
    domain with a discoverer."""
    report = PatternAVReport()

    try:
        # Triggers per-domain discoverer self-registration
        from core.automation import (  # noqa: F401
            discoverer_registry,
        )
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS, DOMAIN_FIRING_MODE,
        )
        from core.automation.payload_discoverer import (
            registered_domains,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAVViolation(
            domain="",
            reason=f"import failed: {exc!s:.150}",
        ))
        return report

    report.registered_discoverers = registered_domains()
    report.substrate_domains = sorted(
        d for d, m in DOMAIN_FIRING_MODE.items()
        if m == "substrate"
    )
    report.engine_domains = sorted(
        d for d, m in DOMAIN_FIRING_MODE.items()
        if m == "engine"
    )

    known = set(DOMAIN_APPLY_FLAGS.keys())
    engine = set(report.engine_domains)
    registered = set(report.registered_discoverers)

    # Drift class 1: registered for unknown domain
    for d in sorted(registered - known):
        report.violations.append(PatternAVViolation(
            domain=d,
            reason=(
                f"discoverer registered for unknown domain "
                f"{d!r}; not in DOMAIN_APPLY_FLAGS"
            ),
        ))

    # Drift class 2: registered for engine-mode domain
    for d in sorted(registered & engine):
        report.violations.append(PatternAVViolation(
            domain=d,
            reason=(
                f"discoverer registered for engine-mode "
                f"domain {d!r}; engine flow.py already "
                "emits payload -- discoverer is wasted"
            ),
        ))

    # Informational: substrate-mode without a discoverer (no
    # violation, but useful for the report).
    substrate = set(report.substrate_domains)
    report.substrate_without_discoverer = sorted(
        substrate - registered
    )

    # Clean pairings: substrate-mode with a discoverer
    report.clean_pairings = sorted(substrate & registered)

    return report
