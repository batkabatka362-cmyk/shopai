"""Pattern BX audit: empire-dashboard guardrail overrides (W929).

Companion to [[pattern-bw]] (per-store substrate + status
CLI). BX guards the W928 empire-dashboard surfacing.

Invariants:

  1. cli.py builds ``guardrail_override_block`` for the
     empire dashboard.
  2. JSON envelope includes ``guardrail_overrides`` key.
  3. Text mode renders the ``guardrail-override:`` row +
     drill hint to ``shopai thrash-guardrail``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBXViolation:
    invariant: str
    reason: str


@dataclass
class PatternBXReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBXViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBXReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBXViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bx_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBXReport:
    """Verify the W928 empire-dashboard guardrail-override row."""
    report = PatternBXReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: builds guardrail_override_block
    _check(
        report, "builds_guardrail_override_block",
        _file_references(
            cli_path,
            "guardrail_override_block",
            "thrash_guardrail_enabled",
        ),
        (
            "cli.py empire dashboard does not build "
            "guardrail_override_block"
        ),
    )

    # 2: JSON envelope key
    _check(
        report, "json_envelope_carries_overrides",
        _file_references(
            cli_path,
            '"guardrail_overrides": guardrail_override_block',
        ),
        (
            "JSON envelope does not include "
            "guardrail_overrides key"
        ),
    )

    # 3: text row + drill hint
    _check(
        report, "renders_override_row_with_drill",
        _file_references(
            cli_path,
            "guardrail-override:",
            "shopai thrash-guardrail",
        ),
        (
            "cli.py empire does not render the "
            "guardrail-override row + drill hint"
        ),
    )

    return report
