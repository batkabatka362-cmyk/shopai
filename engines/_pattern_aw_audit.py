"""Pattern AW audit: discoverer return-shape parity (W826).

Pattern AV (W823) verifies WHO can register a discoverer.
Pattern AW verifies WHAT each discoverer returns:

  1. Calling the discoverer must produce a ``DiscoveryResult``.
  2. ``result.domain`` must equal the registered key (catches
     copy-paste bugs where a new discoverer mis-labels its
     output domain).
  3. ``result.payload`` must be a ``list[dict]`` (already
     enforced by ``discover()`` but Pattern AW makes the
     contract a CI gate).
  4. Source must be a non-empty string when ok=True (audit
     trail).

The audit invokes each discoverer with whatever Shopify state
exists -- in the standard test/dev environment, fetches return
empty so payloads are empty + ok=True. Runtime check, not AST.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternAWViolation:
    domain: str
    reason: str


@dataclass
class PatternAWReport:
    discoverers_scanned: list[str] = field(default_factory=list)
    clean_discoverers: list[str] = field(default_factory=list)
    violations: list[PatternAWViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_aw_audit() -> PatternAWReport:
    """Invoke every registered discoverer + verify its return
    shape obeys the contract."""
    report = PatternAWReport()

    try:
        from core.automation import (  # noqa: F401
            discoverer_registry,
        )
        from core.automation.payload_discoverer import (
            DiscoveryResult, _DISCOVERERS,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAWViolation(
            domain="",
            reason=f"import failed: {exc!s:.150}",
        ))
        return report

    for domain in sorted(_DISCOVERERS):
        report.discoverers_scanned.append(domain)
        fn = _DISCOVERERS[domain]
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    f"discoverer raised on invocation: "
                    f"{exc!s:.150}"
                ),
            ))
            continue
        if not isinstance(result, DiscoveryResult):
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    f"returned {type(result).__name__}, "
                    "expected DiscoveryResult"
                ),
            ))
            continue
        if result.domain != domain:
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    f"result.domain == {result.domain!r}, "
                    f"expected {domain!r}"
                ),
            ))
            continue
        if not isinstance(result.payload, list):
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    f"payload is {type(result.payload).__name__}"
                    ", expected list"
                ),
            ))
            continue
        bad_row = next(
            (
                (i, r) for i, r in enumerate(result.payload)
                if not isinstance(r, dict)
            ),
            None,
        )
        if bad_row is not None:
            i, r = bad_row
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    f"payload[{i}] is {type(r).__name__}, "
                    "expected dict"
                ),
            ))
            continue
        if result.ok and not result.source:
            report.violations.append(PatternAWViolation(
                domain=domain,
                reason=(
                    "ok=True but source is empty -- every "
                    "discoverer must document where its "
                    "payload originated"
                ),
            ))
            continue
        report.clean_discoverers.append(domain)

    return report
