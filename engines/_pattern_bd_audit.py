"""Pattern BD audit: cooldown UX consistency (W864).

Verifies the operator-facing pieces of the cooldown chain are
all present + wired together. Where Pattern BB (W857) audits
auto-disarm and Pattern BC (W861) audits the cooldown gate,
Pattern BD audits the EXIT path: the operator's escape hatches.

Invariants:

  1. ``substrate_fire_disarm_log.clear_history`` is callable.
  2. ``cli.py`` registers the ``autonomy-cooldown-clear``
     subparser (operator nuclear).
  3. ``cli.py`` registers the ``autonomy-arm`` subparser
     with a ``--force`` flag.
  4. ``autonomy_armed.arm`` documents the ``force`` parameter
     (lightweight: docstring mentions force).
  5. ``cli.py _cmd_autonomy_arm`` references ``ArmCooldownError``
     (cooldown error surfaces gracefully).

If any link is missing: the operator has no way to recover
from a stuck cooldown OR the --force override doesn't actually
plumb through.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBDViolation:
    invariant: str
    reason: str


@dataclass
class PatternBDReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBDViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBDReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBDViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bd_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBDReport:
    """Verify cooldown UX has every required hook."""
    report = PatternBDReport()
    root = Path(repo_root).resolve()

    # 1: clear_history callable
    try:
        from core.automation.substrate_fire_disarm_log import (  # noqa
            clear_history,
        )
        _check(
            report, "clear_history_callable",
            callable(clear_history),
            "clear_history not callable",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBDViolation(
            invariant="disarm_log_import",
            reason=f"import failed: {exc!s:.150}",
        ))

    # 2-3 + 5: cli.py wiring
    cli_path = root / "cli.py"
    _check(
        report, "cli_registers_cooldown_clear",
        _file_references(
            cli_path, "autonomy-cooldown-clear",
        ),
        (
            "cli.py does not register autonomy-cooldown-clear "
            "-- operator has no clear path to reset"
        ),
    )
    _check(
        report, "cli_arm_has_force_flag",
        _file_references(
            cli_path,
            "autonomy_arm_p.add_argument",
            "--force",
        ),
        (
            "cli.py autonomy-arm does not register a --force "
            "flag -- operator override is unreachable"
        ),
    )
    _check(
        report, "cli_arm_handles_cooldown_error",
        _file_references(cli_path, "ArmCooldownError"),
        (
            "cli.py _cmd_autonomy_arm does not reference "
            "ArmCooldownError -- cooldown error surfaces as "
            "an uncaught exception instead of a graceful "
            "message"
        ),
    )

    # 4: arm() documents force
    armed_path = (
        root / "core" / "automation" / "autonomy_armed.py"
    )
    _check(
        report, "arm_documents_force",
        _file_references(armed_path, "force"),
        (
            "autonomy_armed.py does not mention 'force' -- "
            "the override path is invisible to readers"
        ),
    )

    return report
