"""Pattern BT audit: thrash noise filter + per-store empire (W914).

Companion to [[pattern-bs]] (basic empire thrash surface).
BS guards the fleet-only row + history --store; BT guards
the W912 --above-threshold filter + W913 per-store empire
breakdown.

Invariants:

  1. CLI registers ``--above-threshold`` flag on the
     autonomy-overview-history subparser.
  2. CLI handler honors ``--above-threshold`` by filtering
     to elevated/thrashing buckets (text reference token).
  3. JSON envelope includes ``above_threshold`` boolean.
  4. Empire dashboard thrash_block builds ``per_store``
     sub-list (compute_thrash called with store_id inside
     the empire stores_list loop).
  5. Empire text mode renders ``thrash per-store:`` row
     with drill hint variant ``[--store X]``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBTViolation:
    invariant: str
    reason: str


@dataclass
class PatternBTReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBTViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBTReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBTViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bt_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBTReport:
    """Verify the W912-913 noise filter + per-store surfaces."""
    report = PatternBTReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: --above-threshold flag registered
    _check(
        report, "cli_registers_above_threshold_flag",
        _file_references(
            cli_path,
            "autonomy_overview_history_p.add_argument",
            '"--above-threshold"',
        ),
        (
            "cli.py does not register --above-threshold on "
            "autonomy_overview_history_p"
        ),
    )

    # 2: handler honors --above-threshold
    _check(
        report, "handler_honors_above_threshold",
        _file_references(
            cli_path,
            "above_threshold",
            'b.density_label',
            '("elevated", "thrashing")',
        ),
        (
            "cli.py handler does not gate bucket render by "
            "elevated/thrashing density_label"
        ),
    )

    # 3: JSON envelope includes above_threshold
    _check(
        report, "json_envelope_includes_above_threshold",
        _file_references(
            cli_path,
            '"above_threshold": above_only',
        ),
        (
            "JSON envelope does not include above_threshold "
            "boolean"
        ),
    )

    # 4: empire builds per_store breakdown
    _check(
        report, "empire_builds_per_store_breakdown",
        _file_references(
            cli_path,
            'thrash_block["per_store"]',
            "store_id=s[\"store_id\"]",
        ),
        (
            "cli.py empire dashboard does not iterate "
            "stores_list to populate thrash_block per_store"
        ),
    )

    # 5: empire renders per-store row + drill hint variant
    _check(
        report, "empire_renders_per_store_row",
        _file_references(
            cli_path,
            "thrash per-store:",
            "--thrash [--store X]",
        ),
        (
            "cli.py empire does not render per-store thrash "
            "row + per-store drill hint"
        ),
    )

    return report
