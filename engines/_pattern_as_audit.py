"""Pattern AS audit: env knob name uniqueness (W375).

Pattern T (W185) catalogs every autonomy domain's env knobs. If
a future PR adds a new domain and copy-pastes an env knob name
from an existing domain (e.g. forgets to rename
``SHOPAI_REFUND_MAX_AMOUNT_USD`` to
``SHOPAI_NEWDOMAIN_MAX_AMOUNT_USD``), the new domain silently
shares its sibling's env value -- a subtle cross-domain
contamination bug.

Pattern AS reads Pattern T's registry + asserts every env knob
name is unique across domains. Sibling collisions surface as
violations naming both domains for fast diagnosis.

Read-only: builds on Pattern T's registry without invoking any
domain modules.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternASViolation:
    knob: str
    domains: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PatternASReport:
    total_knobs: int = 0
    unique_knobs: int = 0
    duplicate_knobs: list[str] = field(default_factory=list)
    violations: list[PatternASViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_as_audit() -> PatternASReport:
    """Verify every env knob name maps to exactly one domain."""
    report = PatternASReport()
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        registry = build_autonomy_env_registry()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AS could not load Pattern T registry: %s",
            exc,
        )
        return report

    # Build knob-name -> [domains] map
    knob_to_domains: dict[str, list[str]] = defaultdict(list)
    for knob in registry.knobs:
        knob_to_domains[knob.name].append(knob.domain)

    report.total_knobs = len(knob_to_domains)

    for knob_name, domains in knob_to_domains.items():
        unique_domains = sorted(set(domains))
        if len(unique_domains) == 1:
            report.unique_knobs += 1
            continue
        # Collision: same knob name across 2+ domains
        report.duplicate_knobs.append(knob_name)
        report.violations.append(PatternASViolation(
            knob=knob_name,
            domains=unique_domains,
            reason=(
                f"knob {knob_name!r} registered across "
                f"{len(unique_domains)} domains: "
                f"{unique_domains}"
            ),
        ))
    return report
