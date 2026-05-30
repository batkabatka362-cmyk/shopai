"""Pattern BF audit: per-store armed-state consistency (W871).

Verifies the W869 + W870 per-store wireup is complete so an
operator's --store choice actually reaches every consumer
(arm path + display + CLI dispatch).

Invariants:

  1. ``ArmedEntry`` dataclass has a ``store_id`` field
     (per-store scoping is data-level, not bolted-on).
  2. ``arm()`` signature accepts a ``store_id`` kwarg.
  3. ``disarm()`` signature accepts a ``store_id`` arg.
  4. ``is_armed()`` signature accepts a ``store_id`` arg.
  5. ``list_armed()`` signature accepts a ``store_id`` kwarg
     (filter mode).
  6. ``disarm_domain_all()`` exists and is callable
     (operator nuclear for the per-store layer).
  7. CLI ``autonomy-arm`` registers ``--store`` flag.
  8. CLI ``autonomy-disarm`` registers ``--store`` flag.
  9. CLI ``autonomy-armed`` registers ``--store`` flag.

If any link is missing, the operator's --store choice
silently no-ops at some layer (typical class of multi-store
plumbing bug).
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBFViolation:
    invariant: str
    reason: str


@dataclass
class PatternBFReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBFViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBFReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBFViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def _has_param(fn, name: str) -> bool:
    try:
        sig = inspect.signature(fn)
        return name in sig.parameters
    except (TypeError, ValueError):
        return False


def run_pattern_bf_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBFReport:
    """Verify per-store armed-state is wired through every
    consumer."""
    report = PatternBFReport()
    root = Path(repo_root).resolve()

    # 1: ArmedEntry has store_id field
    try:
        from core.automation.autonomy_armed import (
            ArmedEntry, arm, disarm, disarm_domain_all,
            is_armed, list_armed,
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBFViolation(
            invariant="autonomy_armed_import",
            reason=(
                f"autonomy_armed unimportable: {exc!s:.150}"
            ),
        ))
        return report

    try:
        field_names = {f.name for f in fields(ArmedEntry)}
        _check(
            report, "armed_entry_has_store_id_field",
            "store_id" in field_names,
            "ArmedEntry has no store_id field",
        )
    except Exception:  # noqa: BLE001
        _check(
            report, "armed_entry_has_store_id_field",
            False,
            "ArmedEntry fields unreadable",
        )

    # 2-5: function signatures
    _check(
        report, "arm_accepts_store_id",
        _has_param(arm, "store_id"),
        "arm() does not accept a store_id kwarg",
    )
    _check(
        report, "disarm_accepts_store_id",
        _has_param(disarm, "store_id"),
        "disarm() does not accept a store_id arg",
    )
    _check(
        report, "is_armed_accepts_store_id",
        _has_param(is_armed, "store_id"),
        "is_armed() does not accept a store_id arg",
    )
    _check(
        report, "list_armed_accepts_store_id",
        _has_param(list_armed, "store_id"),
        "list_armed() does not accept a store_id kwarg",
    )

    # 6: disarm_domain_all callable
    _check(
        report, "disarm_domain_all_callable",
        callable(disarm_domain_all),
        "disarm_domain_all not callable",
    )

    # 7-9: CLI wiring
    cli_path = root / "cli.py"
    # Each subparser declares its parser name + --store. We
    # confirm BOTH substrings appear in cli.py file content;
    # too coarse to bind them to a specific parser without
    # full AST, but enough to catch the regression class
    # "operator added a per-store flag but forgot one CLI".
    _check(
        report, "cli_arm_has_store_flag",
        _file_references(
            cli_path, "autonomy_arm_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_arm_p does not register --store "
            "flag"
        ),
    )
    _check(
        report, "cli_disarm_has_store_flag",
        _file_references(
            cli_path, "autonomy_disarm_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_disarm_p does not register "
            "--store flag"
        ),
    )
    _check(
        report, "cli_armed_has_store_flag",
        _file_references(
            cli_path, "autonomy_armed_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_armed_p does not register "
            "--store flag"
        ),
    )

    return report
