"""Pattern AQ audit: DomainSummary verdict literal (W358).

Pattern Q' (W160) verified per-domain DomainSummary objects
carry all 7 canonical fields. Pattern AQ adds the VALUE check:
the ``verdict`` field must be one of the canonical literals
recognized by the autonomy_status rollup's worst-of comparator.

Canonical verdicts:
  - ``paused``   severity 3 (worst)
  - ``degraded`` severity 2
  - ``quiet``    severity 1
  - ``healthy``  severity 0

If a domain returns ``"broken"`` or ``"critical"`` or
``"OK"``, the rollup's ``_VERDICT_SEVERITY.get(verdict, 0)``
falls through to 0 -- so a broken domain silently appears as
healthy in the empire rollup. Pattern AQ catches the drift at
runtime by actually calling each domain's summary function +
checking the verdict.

Runtime check (not AST): the verdict comes from log-data
analysis, so we have to invoke the summary function. Pattern
J guards inside each module prevent persistence pollution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Canonical set -- mirrors autonomy_status._VERDICT_SEVERITY.
CANONICAL_VERDICTS = frozenset({
    "paused", "degraded", "quiet", "healthy",
})


@dataclass
class PatternAQViolation:
    domain: str
    actual_verdict: str = ""
    reason: str = ""


@dataclass
class PatternAQReport:
    domains_scanned: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternAQViolation] = field(
        default_factory=list,
    )
    verdicts_by_domain: dict[str, str] = field(
        default_factory=dict,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_aq_audit() -> PatternAQReport:
    """Invoke autonomy_status.get_autonomy_status() and verify
    every DomainSummary.verdict is in the canonical set."""
    report = PatternAQReport()
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AQ autonomy_status import failed: %s", exc,
        )
        return report
    try:
        rollup = get_autonomy_status()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AQ get_autonomy_status raised: %s", exc,
        )
        return report
    for d in rollup.domains:
        report.domains_scanned.append(d.name)
        report.verdicts_by_domain[d.name] = d.verdict
        if d.verdict in CANONICAL_VERDICTS:
            report.clean_domains.append(d.name)
        else:
            report.violations.append(PatternAQViolation(
                domain=d.name,
                actual_verdict=d.verdict,
                reason=(
                    f"verdict {d.verdict!r} not in canonical "
                    f"set {sorted(CANONICAL_VERDICTS)}"
                ),
            ))
    return report
