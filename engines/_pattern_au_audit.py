"""Pattern AU audit: autonomy_fire catalog parity (W819).

Phase 38 added ``core/automation/autonomy_fire._DOMAIN_APPLIERS``
mapping each autonomy domain to its applier module + function.
That catalog is a 4th cross-cutting registry that drifts the
moment a new domain ships and someone forgets to register it.

Pattern AU is the cardinality + identity parity check:

  1. ``autonomy_fire._DOMAIN_APPLIERS.keys()`` must equal
     ``autonomy_armed.DOMAIN_APPLY_FLAGS.keys()`` exactly.
     Catches "added domain to one catalog but not the other".

  2. Every applier referenced in autonomy_fire must actually
     import cleanly + expose the named callable. Catches drift
     when an applier is renamed in its module but the catalog
     entry was not updated.

This is companion to Pattern AR (cross-catalog cardinality
across 24+ catalogs) but specifically targets autonomy_fire +
autonomy_armed since they're the two operator-facing registries
the autonomy-arm/fire/armed CLIs depend on.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternAUViolation:
    domain: str
    reason: str


@dataclass
class PatternAUReport:
    domains_in_fire_catalog: list[str] = field(
        default_factory=list,
    )
    domains_in_armed_catalog: list[str] = field(
        default_factory=list,
    )
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAUViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_au_audit() -> PatternAUReport:
    """Verify autonomy_fire + autonomy_armed catalogs agree and
    every fire entry resolves to a callable."""
    report = PatternAUReport()

    try:
        from core.automation.autonomy_fire import (
            _DOMAIN_APPLIERS,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAUViolation(
            domain="",
            reason=f"autonomy_fire import failed: {exc!s:.150}",
        ))
        return report

    try:
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAUViolation(
            domain="",
            reason=(
                f"autonomy_armed import failed: {exc!s:.150}"
            ),
        ))
        return report

    fire_keys = set(_DOMAIN_APPLIERS.keys())
    armed_keys = set(DOMAIN_APPLY_FLAGS.keys())
    report.domains_in_fire_catalog = sorted(fire_keys)
    report.domains_in_armed_catalog = sorted(armed_keys)

    # Symmetric-difference parity check
    missing_in_fire = armed_keys - fire_keys
    missing_in_armed = fire_keys - armed_keys
    for d in sorted(missing_in_fire):
        report.violations.append(PatternAUViolation(
            domain=d,
            reason=(
                "in autonomy_armed.DOMAIN_APPLY_FLAGS but "
                "NOT in autonomy_fire._DOMAIN_APPLIERS -- "
                "add the (module, fn) entry"
            ),
        ))
    for d in sorted(missing_in_armed):
        report.violations.append(PatternAUViolation(
            domain=d,
            reason=(
                "in autonomy_fire._DOMAIN_APPLIERS but NOT "
                "in autonomy_armed.DOMAIN_APPLY_FLAGS -- "
                "add an apply_X flag tuple"
            ),
        ))

    # Resolve each fire-catalog entry to a callable
    for domain in sorted(fire_keys):
        mod_path, fn_name = _DOMAIN_APPLIERS[domain]
        try:
            mod = importlib.import_module(mod_path)
        except Exception as exc:  # noqa: BLE001
            report.violations.append(PatternAUViolation(
                domain=domain,
                reason=(
                    f"import {mod_path} failed: {exc!s:.120}"
                ),
            ))
            continue
        fn = getattr(mod, fn_name, None)
        if fn is None or not callable(fn):
            report.violations.append(PatternAUViolation(
                domain=domain,
                reason=(
                    f"{mod_path} has no callable {fn_name!r}"
                ),
            ))
            continue
        if domain not in (
            v.domain for v in report.violations
        ):
            report.clean_domains.append(domain)

    return report
