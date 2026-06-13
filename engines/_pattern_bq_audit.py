"""Pattern BQ audit: autonomy-overview history schema (W902).

Companion to [[pattern-bn]] (current-snapshot schema) and
[[pattern-bp]] (alternate render formats). BQ guards the
W900-901 persisted history layer so future refactors cannot
silently break:

  - the JSON-file row schema (operators may parse the file
    directly with jq / Python)
  - the OverviewHistoryEntry dataclass shape (in-process
    consumers depend on it)
  - the CLI ``autonomy-overview-history`` subparser
    registration + ``--transitions`` flag

Invariants:

  1. ``OverviewHistoryEntry`` exports all expected fields.
  2. ``record_snapshot``, ``recent_entries``,
     ``verdict_transitions``, ``history_size`` exported.
  3. ``record_snapshot`` honors the Pattern J pytest guard
     (writes nothing when ``_is_test_environment`` returns
     True).
  4. CLI ``autonomy-overview-history`` subparser registered.
  5. CLI subparser registers ``--transitions`` flag.

Pattern BQ runs the helpers in a tmp_path to verify the
guard behavior (no synthetic file written), and text-greps
cli.py for the subparser plumbing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)


_EXPECTED_ENTRY_FIELDS = {
    "captured_at", "store_id", "window_hours", "verdict",
    "armed_total", "fires_total", "fires_invoked",
    "fires_errors", "cooldown_blocked", "alerts_critical",
    "alerts_warn",
}


@dataclass
class PatternBQViolation:
    invariant: str
    reason: str


@dataclass
class PatternBQReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBQViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBQReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBQViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bq_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBQReport:
    """Verify the autonomy-overview history layer."""
    report = PatternBQReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: OverviewHistoryEntry field shape
    try:
        from core.automation.autonomy_overview_history import (
            OverviewHistoryEntry,
        )
        entry_field_names = {
            f.name for f in fields(OverviewHistoryEntry)
        }
        missing = _EXPECTED_ENTRY_FIELDS - entry_field_names
        _check(
            report, "entry_has_all_fields",
            len(missing) == 0,
            (
                f"OverviewHistoryEntry missing fields: "
                f"{sorted(missing)}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "entry_has_all_fields", False,
            f"OverviewHistoryEntry import raised: {exc!s:.100}",
        )

    # 2: module exports
    try:
        from core.automation import (
            autonomy_overview_history as _h,
        )
        missing_exports = [
            n for n in (
                "record_snapshot", "recent_entries",
                "verdict_transitions", "history_size",
            )
            if not callable(getattr(_h, n, None))
        ]
        _check(
            report, "module_exports_helpers",
            not missing_exports,
            (
                f"autonomy_overview_history missing "
                f"callables: {missing_exports}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "module_exports_helpers", False,
            f"module import raised: {exc!s:.100}",
        )

    # 3: Pattern J guard honored by record_snapshot.
    # Force-set PYTEST_CURRENT_TEST so the guard fires even
    # when the audit is invoked from a non-pytest context
    # (the CLI runner).
    try:
        import os
        import tempfile
        from core.automation.autonomy_overview import (
            OverviewSnapshot,
        )
        from core.automation import (
            autonomy_overview_history as _h,
        )
        original = os.environ.get("PYTEST_CURRENT_TEST")
        os.environ["PYTEST_CURRENT_TEST"] = "pattern_bq_probe"
        try:
            with tempfile.TemporaryDirectory() as td:
                probe = Path(td) / "p.json"
                _h.record_snapshot(
                    OverviewSnapshot(), path=probe,
                )
                _check(
                    report,
                    "record_snapshot_honors_pytest_guard",
                    not probe.exists(),
                    (
                        "record_snapshot wrote to disk "
                        "despite Pattern J pytest guard"
                    ),
                )
        finally:
            if original is None:
                os.environ.pop("PYTEST_CURRENT_TEST", None)
            else:
                os.environ["PYTEST_CURRENT_TEST"] = original
    except Exception as exc:  # noqa: BLE001
        _check(
            report,
            "record_snapshot_honors_pytest_guard",
            False,
            f"runtime probe raised: {exc!s:.100}",
        )

    # 4: CLI subparser registered
    _check(
        report, "cli_history_subparser_registered",
        _file_references(
            cli_path,
            'autonomy_overview_history_p = sub.add_parser',
        ),
        (
            "cli.py does not register "
            "autonomy_overview_history_p subparser"
        ),
    )

    # 5: --transitions flag registered
    _check(
        report, "cli_registers_transitions_flag",
        _file_references(
            cli_path,
            "autonomy_overview_history_p.add_argument",
            '"--transitions"',
        ),
        (
            "cli.py does not register --transitions on "
            "autonomy_overview_history_p"
        ),
    )

    return report
