"""Pattern BG audit: per-store CLI plumbing breadth (W874).

Verifies every operator-facing CLI surface that documents a
``--store`` flag actually plumbs the value through to its
downstream callee. Pattern BF (W871) audited the arm/disarm/
armed trio. Pattern BG audits the read-side fleet:

  - autonomy-status
  - autonomy-doctor
  - autonomy-kpi
  - autonomy-alerts
  - autonomy-fire-status
  - autonomy-fire-trend

Each must:
  1. Register a ``--store`` flag in its subparser.
  2. Pass the store value into the corresponding substrate
     call (compute_*, get_autonomy_status, ...).

If any link breaks: operator's ``--store=X`` choice silently
gets ignored at the report-generation layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Each entry: (cli_subparser_name, downstream_substrate_fn,
#              expected_kwarg_token_in_cli_handler)
_CLI_SURFACES: list[tuple[str, str, str]] = [
    (
        "autonomy_status_p",
        "get_autonomy_status",
        "store_id=",
    ),
    (
        "autonomy_doctor_p",
        "run_autonomy_doctor",
        "store_id=",
    ),
    (
        "autonomy_kpi_p",
        "compute_fire_kpis",
        "store_id=",
    ),
    (
        "autonomy_alerts_p",
        "compute_fire_alerts",
        "store_id=",
    ),
    (
        "autonomy_fire_status_p",
        "recent_substrate_fires",
        "store_id=",
    ),
    (
        "autonomy_fire_trend_p",
        "compute_fire_trend",
        "store_id=",
    ),
]


@dataclass
class PatternBGViolation:
    invariant: str
    reason: str


@dataclass
class PatternBGReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBGViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBGReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBGViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bg_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBGReport:
    """Verify per-store CLI plumbing across the read-side
    fleet of autonomy subcommands."""
    report = PatternBGReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    for parser, downstream_fn, plumb_token in _CLI_SURFACES:
        # Each surface must declare --store on its parser AND
        # pass store_id= to its downstream substrate call.
        has_flag = _file_references(
            cli_path,
            f"{parser}.add_argument",
            '"--store"',
        )
        has_plumb = _file_references(
            cli_path, downstream_fn, plumb_token,
        )
        _check(
            report, f"{parser}_has_store_flag",
            has_flag,
            (
                f"cli.py {parser} does not register --store "
                "flag"
            ),
        )
        _check(
            report, f"{parser}_plumbs_store_id",
            has_plumb,
            (
                f"cli.py does not pass store_id= alongside "
                f"{downstream_fn}() -- operator --store "
                "silently ignored"
            ),
        )

    return report
