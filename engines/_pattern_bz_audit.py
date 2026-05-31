"""Pattern BZ audit: daily-brief thrash blocks row (W935).

Companion to [[pattern-bo]] (daily-brief autonomy row).
BZ guards the W934 surfacing of the W930 block log on the
daily-brief surface.

Invariants:

  1. daily-brief references ``recent_blocks`` (the block
     log read API).
  2. daily-brief renders the canonical ``Thrash blocks:``
     row prefix.
  3. daily-brief includes the ``shopai thrash-blocks``
     drill hint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBZViolation:
    invariant: str
    reason: str


@dataclass
class PatternBZReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBZViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBZReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBZViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bz_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBZReport:
    """Verify the W934 daily-brief thrash-blocks row."""
    report = PatternBZReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: imports recent_blocks
    _check(
        report, "daily_brief_imports_recent_blocks",
        _file_references(
            cli_path, "recent_blocks", "thrash_block_log",
        ),
        (
            "cli.py daily-brief block does not import "
            "recent_blocks from thrash_block_log"
        ),
    )

    # 2: row prefix
    _check(
        report, "daily_brief_renders_blocks_row",
        _file_references(
            cli_path, '"  Thrash blocks:',
        ),
        (
            "cli.py daily-brief does not render the "
            "'  Thrash blocks:' row prefix"
        ),
    )

    # 3: drill hint
    _check(
        report, "daily_brief_shows_drill_hint",
        _file_references(
            cli_path, "shopai thrash-blocks",
        ),
        (
            "cli.py daily-brief omits the "
            "'shopai thrash-blocks' drill hint"
        ),
    )

    return report
