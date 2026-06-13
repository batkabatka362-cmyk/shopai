"""Pattern BC audit: re-arm cooldown chain (W861).

Verifies the W858 + W859 cooldown chain so an auto-disarmed
domain genuinely refuses to be re-armed within the cooldown
window.

Invariants:

  1. ``substrate_fire_disarm_log.record_disarm_decisions`` is
     callable.
  2. ``substrate_fire_disarm_log.last_disarm_at`` is callable.
  3. ``autonomy_armed.ArmCooldownError`` exists + is a class.
  4. ``substrate_fire_auto_disarm`` references
     ``record_disarm_decisions`` (decisions actually persist).
  5. ``autonomy_armed.arm`` references
     ``last_disarm_at`` (cooldown check actually fires).
  6. ``autonomy_armed.arm`` accepts a ``force`` kwarg
     (operator override is wired through).

If any link is broken: bridge actions vanish from history OR
arm() silently bypasses the cooldown OR --force has no effect.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBCViolation:
    invariant: str
    reason: str


@dataclass
class PatternBCReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBCViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBCReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBCViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bc_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBCReport:
    """Verify the cooldown chain has every required hook."""
    report = PatternBCReport()
    root = Path(repo_root).resolve()

    # 1-2: disarm log callables
    try:
        from core.automation.substrate_fire_disarm_log import (  # noqa
            last_disarm_at,
            record_disarm_decisions,
        )
        _check(
            report, "record_decisions_callable",
            callable(record_disarm_decisions),
            "record_disarm_decisions not callable",
        )
        _check(
            report, "last_disarm_at_callable",
            callable(last_disarm_at),
            "last_disarm_at not callable",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBCViolation(
            invariant="disarm_log_import",
            reason=(
                f"disarm_log unimportable: {exc!s:.150}"
            ),
        ))

    # 3: ArmCooldownError exists
    try:
        from core.automation.autonomy_armed import (
            ArmCooldownError, arm,
        )
        _check(
            report, "arm_cooldown_error_class",
            isinstance(ArmCooldownError, type)
            and issubclass(ArmCooldownError, Exception),
            "ArmCooldownError missing / not a class",
        )

        # 6: arm accepts force kwarg
        try:
            sig = inspect.signature(arm)
            _check(
                report, "arm_force_kwarg",
                "force" in sig.parameters,
                "arm() does not accept a 'force' kwarg",
            )
        except (TypeError, ValueError):
            _check(
                report, "arm_force_kwarg",
                False,
                "arm() signature unreadable",
            )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBCViolation(
            invariant="autonomy_armed_import",
            reason=(
                f"autonomy_armed unimportable: "
                f"{exc!s:.150}"
            ),
        ))

    # 4: auto_disarm records
    auto_disarm_path = (
        root / "core" / "automation"
        / "substrate_fire_auto_disarm.py"
    )
    _check(
        report, "auto_disarm_records_decisions",
        _file_references(
            auto_disarm_path, "record_disarm_decisions",
        ),
        (
            "substrate_fire_auto_disarm doesn't reference "
            "record_disarm_decisions -- decisions never "
            "persist"
        ),
    )

    # 5: arm reads
    armed_path = (
        root / "core" / "automation" / "autonomy_armed.py"
    )
    _check(
        report, "arm_reads_disarm_log",
        _file_references(
            armed_path, "last_disarm_at",
        ),
        (
            "autonomy_armed.arm doesn't reference "
            "last_disarm_at -- cooldown check never fires"
        ),
    )

    return report
