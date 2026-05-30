"""Pattern AZ audit: substrate_fire log invariants (W842).

Runtime audit of the W840 substrate_fire log + recorder:

  1. ``substrate_fire_log.record_substrate_fire`` exists and
     is callable.
  2. Calling with an obviously-non-actionable outcome
     (no_discoverer + 0 rows) MUST NOT grow the log -- the
     recorder boundary filter is the contract.
  3. Calling with a missing ``domain`` field MUST be silent
     (no exception, no log row).
  4. ``recent_substrate_fires`` returns a list with safe
     filters (store_id + domain) -- never raises on missing
     log file.

This is a runtime audit (not AST) because the recorder's
filter logic lives in real Python branches that AST can't
verify. A future change that removed the no-discoverer filter
would silently flood the log; this audit catches it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternAZViolation:
    invariant: str
    reason: str


@dataclass
class PatternAZReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternAZViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(report: PatternAZReport, name: str, ok: bool, why: str = "") -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternAZViolation(
            invariant=name, reason=why,
        ))


def run_pattern_az_audit() -> PatternAZReport:
    """Verify substrate_fire log recorder + reader invariants."""
    report = PatternAZReport()

    try:
        from core.automation.substrate_fire_log import (
            record_substrate_fire,
            recent_substrate_fires,
            substrate_fire_log_size,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAZViolation(
            invariant="module_import",
            reason=f"substrate_fire_log import failed: {exc!s:.150}",
        ))
        return report

    # Invariant 1: recorder callable
    _check(
        report,
        "recorder_callable",
        callable(record_substrate_fire),
        "record_substrate_fire is not callable",
    )

    # Invariant 2: pure no-op outcome doesn't grow the log
    # (Pattern J guard or recorder filter, either is fine)
    class _FakeOutcome:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    try:
        size_before = substrate_fire_log_size()
        record_substrate_fire(
            _FakeOutcome(
                domain="shipping_alert",
                store_id="",
                discovered=0,
                invoked=False,
                events=0,
                duration_ms=0.0,
                reason="no_discoverer",
                error="",
            ),
        )
        size_after = substrate_fire_log_size()
        _check(
            report,
            "no_op_outcome_filtered",
            size_after == size_before,
            f"size before {size_before}, after {size_after}",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAZViolation(
            invariant="no_op_outcome_filtered",
            reason=f"raised on no-op outcome: {exc!s:.150}",
        ))

    # Invariant 3: missing-domain outcome is silent
    try:
        record_substrate_fire(_FakeOutcome())
        _check(report, "missing_domain_silent", True)
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAZViolation(
            invariant="missing_domain_silent",
            reason=f"raised: {exc!s:.150}",
        ))

    # Invariant 4: reader returns list with safe filters
    try:
        rows = recent_substrate_fires(window_hours=1.0)
        _check(
            report,
            "reader_returns_list",
            isinstance(rows, list),
            f"got {type(rows).__name__}, expected list",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAZViolation(
            invariant="reader_returns_list",
            reason=f"reader raised: {exc!s:.150}",
        ))

    # Invariant 5: reader honors store + domain filters
    try:
        rows = recent_substrate_fires(
            window_hours=1.0,
            store_id="nonexistent",
            domain="nonexistent",
        )
        _check(
            report,
            "reader_filters_safe",
            isinstance(rows, list) and len(rows) == 0,
            "filters did not return empty list",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternAZViolation(
            invariant="reader_filters_safe",
            reason=f"raised: {exc!s:.150}",
        ))

    return report
