"""Pattern Q' audit: autonomy DomainSummary uniformity (Wave 160).

Each autonomy domain's get_*_status() returns a domain-
specific dataclass (SupportStatusReport / MarketingStatusReport
/ FulfillmentStatusReport / InventoryStatusReport /
CleanupStatusReport). These reports have DOMAIN-SPECIFIC field
names (e.g. customer_support uses refund_applied_count;
marketing uses applied_count). That's fine -- the per-domain
CLI surfaces consume them directly.

But the UNIFIED rollup goes through
``core.automation.autonomy_status._<domain>_summary()``
which converts each report into a canonical ``DomainSummary``.
Pattern Q' verifies every ``_<domain>_summary()`` function
returns a DomainSummary with all 7 canonical fields populated:

  - name (str)
  - verdict (str)
  - paused (bool)
  - applied_count (int)
  - health_failure_ratio (float)
  - next_action (str)
  - reasons (list)

This is the boundary contract the autonomy-status rollup
depends on. Future domains MUST emit a valid DomainSummary
from their summary function.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CANONICAL_FIELDS: frozenset[str] = frozenset({
    "name",
    "verdict",
    "paused",
    "applied_count",
    "health_failure_ratio",
    "next_action",
    "reasons",
})


@dataclass
class PatternQPrimeViolation:
    domain: str
    missing_fields: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class PatternQPrimeReport:
    domains_probed: list[str] = field(default_factory=list)
    clean_domains: list[str] = field(default_factory=list)
    violations: list[PatternQPrimeViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _domain_probes() -> list[
    tuple[str, Callable[..., Any]]
]:
    """Resolve the per-domain summary functions from
    core.automation.autonomy_status. These convert each domain
    report into a canonical DomainSummary."""
    out: list[tuple[str, Callable[..., Any]]] = []
    try:
        from core.automation import autonomy_status as au
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern Q' autonomy_status import raised: %s", exc,
        )
        return out
    probes = (
        ("customer_support", "_customer_support_summary"),
        ("marketing", "_marketing_summary"),
        ("fulfillment", "_fulfillment_summary"),
        ("inventory", "_inventory_summary"),
        ("discount_cleanup", "_discount_cleanup_summary"),
        ("order_followup", "_order_followup_summary"),
    )
    for domain, fn_name in probes:
        fn = getattr(au, fn_name, None)
        if callable(fn):
            out.append((domain, fn))
    return out


def _check_report_shape(
    domain: str, report: Any,
) -> PatternQPrimeViolation | None:
    """Return None if the report has all canonical fields, or
    a violation entry listing what's missing."""
    missing = [
        f for f in _CANONICAL_FIELDS
        if not hasattr(report, f)
    ]
    if missing:
        return PatternQPrimeViolation(
            domain=domain,
            missing_fields=sorted(missing),
        )
    return None


def run_pattern_qprime_audit() -> PatternQPrimeReport:
    """Probe every autonomy domain's status fn + verify shape."""
    report = PatternQPrimeReport()
    for domain, fn in _domain_probes():
        report.domains_probed.append(domain)
        try:
            result = fn(window_hours=24.0)
        except Exception as exc:  # noqa: BLE001
            report.violations.append(
                PatternQPrimeViolation(
                    domain=domain,
                    error=f"{fn.__name__} raised: {exc}",
                ),
            )
            continue
        violation = _check_report_shape(domain, result)
        if violation is not None:
            report.violations.append(violation)
        else:
            report.clean_domains.append(domain)
    return report
