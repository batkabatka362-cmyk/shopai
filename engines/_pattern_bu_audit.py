"""Pattern BU audit: thrash guardrail substrate (W916).

Companion to the existing AGI guardrail audit family. Guards
the W915 substrate contract — three callables in
``engines/_agi_context`` that future appliers will import.

Invariants:

  1. ``thrash_guardrail_enabled`` exported and reads
     ``SHOPAI_THRASH_GUARDRAIL`` env var (probe with isolation:
     set + clear).
  2. ``should_block_thrashing_store`` exported and respects
     the enabled gate (returns False when disabled).
  3. ``should_block_thrashing_store`` returns False on empty
     store_id even when enabled.
  4. ``explain_thrash_block`` exported and returns a string
     containing the canonical token ``thrash_guardrail_blocked``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternBUViolation:
    invariant: str
    reason: str


@dataclass
class PatternBUReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBUViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBUReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBUViolation(
            invariant=name, reason=why,
        ))


def run_pattern_bu_audit() -> PatternBUReport:
    """Verify the W915 thrash guardrail substrate contract."""
    report = PatternBUReport()

    # 1: enabled() reads SHOPAI_THRASH_GUARDRAIL
    try:
        from engines._agi_context import (
            thrash_guardrail_enabled,
        )
        original = os.environ.get("SHOPAI_THRASH_GUARDRAIL")
        os.environ["SHOPAI_THRASH_GUARDRAIL"] = "1"
        try:
            on = thrash_guardrail_enabled()
        finally:
            if original is None:
                os.environ.pop(
                    "SHOPAI_THRASH_GUARDRAIL", None,
                )
            else:
                os.environ["SHOPAI_THRASH_GUARDRAIL"] = (
                    original
                )
            off_env = os.environ.get(
                "SHOPAI_THRASH_GUARDRAIL", "",
            )
        # When original is unset, off should be False
        if original is None:
            off = thrash_guardrail_enabled()
            _check(
                report, "enabled_reads_env_var",
                on and not off,
                (
                    f"enabled gate misbehaved: on={on} "
                    f"off={off}"
                ),
            )
        else:
            _check(
                report, "enabled_reads_env_var",
                on,
                f"enabled gate returned False with env=1",
            )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "enabled_reads_env_var", False,
            f"raised: {exc!s:.100}",
        )

    # 2: should_block honors the enabled gate
    try:
        from engines._agi_context import (
            should_block_thrashing_store,
        )
        original = os.environ.get("SHOPAI_THRASH_GUARDRAIL")
        os.environ.pop("SHOPAI_THRASH_GUARDRAIL", None)
        try:
            # Without env-var set, should never block
            blocked = should_block_thrashing_store("store-x")
            _check(
                report, "should_block_respects_disabled",
                not blocked,
                (
                    "should_block_thrashing_store returned "
                    "True with guardrail disabled"
                ),
            )
        finally:
            if original is not None:
                os.environ["SHOPAI_THRASH_GUARDRAIL"] = (
                    original
                )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "should_block_respects_disabled", False,
            f"raised: {exc!s:.100}",
        )

    # 3: empty store_id never blocks
    try:
        from engines._agi_context import (
            should_block_thrashing_store,
        )
        original = os.environ.get("SHOPAI_THRASH_GUARDRAIL")
        os.environ["SHOPAI_THRASH_GUARDRAIL"] = "1"
        try:
            blocked_none = should_block_thrashing_store(None)
            blocked_empty = should_block_thrashing_store("")
            _check(
                report,
                "empty_store_id_does_not_block",
                not blocked_none and not blocked_empty,
                (
                    f"empty store_id blocked: "
                    f"None={blocked_none} empty={blocked_empty}"
                ),
            )
        finally:
            if original is None:
                os.environ.pop(
                    "SHOPAI_THRASH_GUARDRAIL", None,
                )
            else:
                os.environ["SHOPAI_THRASH_GUARDRAIL"] = (
                    original
                )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "empty_store_id_does_not_block",
            False, f"raised: {exc!s:.100}",
        )

    # 4: explain carries canonical token
    try:
        from engines._agi_context import explain_thrash_block
        msg = explain_thrash_block("probe-store")
        _check(
            report, "explain_carries_canonical_token",
            "thrash_guardrail_blocked" in msg,
            (
                f"explain_thrash_block missing canonical "
                f"token: got {msg!r}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "explain_carries_canonical_token",
            False, f"raised: {exc!s:.100}",
        )

    return report
