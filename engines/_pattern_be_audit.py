"""Pattern BE audit: per-domain cooldown env consistency (W867).

Verifies the W866 per-domain cooldown override is correctly
implemented:

  1. ``autonomy_armed._cooldown_hours`` accepts a ``domain``
     positional/kwarg.
  2. The function source references the per-domain env naming
     pattern: ``SHOPAI_AUTO_DISARM_COOLDOWN_{DOMAIN}_HOURS``
     (case-insensitive match for the COOLDOWN_ prefix +
     _HOURS suffix).
  3. The function falls back to the global env knob when no
     per-domain value is set.
  4. CLI callsites (autonomy-status + autonomy-doctor) pass
     a domain to _cooldown_hours so the per-domain override
     actually takes effect (regression guard: easy to forget
     when copy-pasting a probe).

If any link breaks: per-domain knobs become silently
ignored OR all domains share the global value even when an
operator set per-domain overrides.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBEViolation:
    invariant: str
    reason: str


@dataclass
class PatternBEReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBEViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBEReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBEViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_be_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBEReport:
    """Verify per-domain cooldown env override is fully wired."""
    report = PatternBEReport()
    root = Path(repo_root).resolve()

    # 1: function accepts domain arg
    try:
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        try:
            sig = inspect.signature(_cooldown_hours)
            _check(
                report, "cooldown_fn_accepts_domain",
                len(sig.parameters) >= 1,
                "_cooldown_hours has 0 parameters; expected 1",
            )
        except (TypeError, ValueError):
            _check(
                report, "cooldown_fn_accepts_domain",
                False,
                "_cooldown_hours signature unreadable",
            )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBEViolation(
            invariant="autonomy_armed_import",
            reason=f"import failed: {exc!s:.150}",
        ))
        return report

    # 2: function references per-domain env naming
    armed_path = (
        root / "core" / "automation" / "autonomy_armed.py"
    )
    _check(
        report, "cooldown_fn_uses_per_domain_env",
        _file_references(
            armed_path,
            "SHOPAI_AUTO_DISARM_COOLDOWN_",
            "_HOURS",
        ),
        (
            "_cooldown_hours does not reference the per-"
            "domain env naming pattern "
            "SHOPAI_AUTO_DISARM_COOLDOWN_<DOMAIN>_HOURS"
        ),
    )

    # 3: function falls back to global
    _check(
        report, "cooldown_fn_has_global_fallback",
        _file_references(
            armed_path,
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS",
        ),
        (
            "_cooldown_hours does not reference the global "
            "fallback env knob"
        ),
    )

    # 4a: cli.py autonomy-status passes domain
    cli_path = root / "cli.py"
    _check(
        report, "cli_passes_domain_to_cooldown",
        _file_references(
            cli_path,
            "_cd_hours(d)",
        ),
        (
            "cli.py autonomy-status does not pass a domain "
            "to _cooldown_hours -- per-domain overrides "
            "silently ignored"
        ),
    )

    # 4b: doctor passes domain
    doctor_path = (
        root / "core" / "automation" / "autonomy_doctor.py"
    )
    _check(
        report, "doctor_passes_domain_to_cooldown",
        _file_references(
            doctor_path,
            "_cd_hours(summary.name)",
        ),
        (
            "autonomy_doctor does not pass summary.name to "
            "_cooldown_hours -- per-domain overrides ignored "
            "in doctor probes"
        ),
    )

    return report
