"""Pattern BO audit: daily-brief autonomy overview row (W895).

Verifies the W894 daily-brief block remains wired:

  1. ``cli.py`` references ``build_overview`` inside the
     daily-brief function (verifies the overview is read).
  2. ``cli.py`` references the canonical "Autonomy:"
     row prefix in daily-brief output.
  3. ``cli.py`` references the drill hint
     "shopai autonomy-overview" so operators have a clear
     path to the full view.

If any link is missing, the operator's daily-brief stops
showing the autonomy verdict + they lose the at-a-glance
health signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBOViolation:
    invariant: str
    reason: str


@dataclass
class PatternBOReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBOViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBOReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBOViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bo_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBOReport:
    """Verify daily-brief autonomy overview surface is wired."""
    report = PatternBOReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    _check(
        report, "daily_brief_imports_build_overview",
        _file_references(
            cli_path,
            "build_overview",
            "daily-brief",
        ),
        (
            "cli.py daily-brief does not import "
            "build_overview"
        ),
    )
    _check(
        report, "daily_brief_renders_autonomy_row",
        _file_references(
            cli_path,
            '"  Autonomy:',
        ),
        (
            'cli.py does not contain the canonical "  '
            'Autonomy:" daily-brief row prefix'
        ),
    )
    _check(
        report, "daily_brief_shows_drill_hint",
        _file_references(
            cli_path, "shopai autonomy-overview",
        ),
        (
            "cli.py does not contain the autonomy-overview "
            "drill hint -- operator lost the clear path "
            "to the full surface"
        ),
    )

    return report
