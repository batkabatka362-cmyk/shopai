"""Pattern BB audit: auto-disarm chain integrity (W857).

Verifies the W853 + W854 chain is fully wired:

  1. ``record_alerts`` exists in alert_history module +
     callable.
  2. ``consecutive_critical_days`` exists + callable.
  3. ``maybe_auto_disarm`` exists in auto_disarm module +
     callable.
  4. ``substrate_fire_alerts.compute_fire_alerts`` calls
     ``record_alerts`` (so alerts actually persist).
  5. ``cli.py _cmd_cycle_run`` references
     ``maybe_auto_disarm`` (so the bridge actually fires).
  6. ``substrate_fire_auto_disarm`` references both
     ``list_armed`` (W815 armed registry) and
     ``consecutive_critical_days`` (W853 history reader).

If any link is broken, alerts vanish into the void OR
auto-disarm never runs even when the env knob is set.

Mostly an AST audit (text-grep for cross-module references)
plus a couple of runtime callable checks. Static like Pattern
U + V; complements Pattern AZ (substrate_fire_log invariants).
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBBViolation:
    invariant: str
    reason: str


@dataclass
class PatternBBReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBBViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBBReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBBViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    """Returns True iff ALL symbols appear in the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bb_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBBReport:
    """Verify the auto-disarm chain is fully wired."""
    report = PatternBBReport()
    root = Path(repo_root).resolve()

    # 1-3: callable invariants (runtime imports)
    try:
        from core.automation.substrate_fire_alert_history import (  # noqa
            consecutive_critical_days,
            record_alerts,
        )
        _check(
            report, "record_alerts_callable",
            callable(record_alerts),
            "record_alerts not callable",
        )
        _check(
            report, "consecutive_critical_days_callable",
            callable(consecutive_critical_days),
            "consecutive_critical_days not callable",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBBViolation(
            invariant="alert_history_import",
            reason=(
                f"alert_history module unimportable: "
                f"{exc!s:.150}"
            ),
        ))

    try:
        from core.automation.substrate_fire_auto_disarm import (  # noqa
            maybe_auto_disarm,
        )
        _check(
            report, "maybe_auto_disarm_callable",
            callable(maybe_auto_disarm),
            "maybe_auto_disarm not callable",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBBViolation(
            invariant="auto_disarm_import",
            reason=(
                f"auto_disarm module unimportable: "
                f"{exc!s:.150}"
            ),
        ))

    # 4: alerter records alerts
    alerts_path = (
        root / "core" / "automation"
        / "substrate_fire_alerts.py"
    )
    _check(
        report, "alerts_records_to_history",
        _file_references(alerts_path, "record_alerts"),
        (
            "substrate_fire_alerts.py does not import "
            "record_alerts -- alerts never persist"
        ),
    )

    # 5: cycle hook fires the bridge
    cli_path = root / "cli.py"
    _check(
        report, "cycle_hook_invokes_bridge",
        _file_references(cli_path, "maybe_auto_disarm"),
        (
            "cli.py does not reference maybe_auto_disarm -- "
            "bridge will never fire even with env set"
        ),
    )

    # 6: auto_disarm wires both inputs
    auto_disarm_path = (
        root / "core" / "automation"
        / "substrate_fire_auto_disarm.py"
    )
    _check(
        report, "auto_disarm_reads_history",
        _file_references(
            auto_disarm_path, "consecutive_critical_days",
        ),
        (
            "auto_disarm doesn't reference "
            "consecutive_critical_days"
        ),
    )
    _check(
        report, "auto_disarm_uses_armed_registry",
        _file_references(
            auto_disarm_path, "list_armed",
        ),
        (
            "auto_disarm doesn't reference list_armed -- "
            "no armed-domain iteration"
        ),
    )

    return report
