"""Pattern BR audit: autonomy-overview thrash detector (W908).

Companion to [[pattern-bp]] (render formats) and
[[pattern-bq]] (history schema). BR guards the W904-907
thrash-detection chain so future refactors cannot break
the verdict-flip alerting path.

Invariants:

  1. ``compute_thrash`` exported and returns a
     ``ThrashReport`` with ``verdict`` + ``buckets``.
  2. ``ThrashReport.verdict`` is one of the documented
     literals (calm / elevated / thrashing).
  3. ``ThrashBucket.density_label`` is one of the
     documented literals.
  4. CLI ``autonomy-overview-history --thrash`` flag
     registered.
  5. ``engines/_notify.py`` references both
     ``autonomy_thrash`` AND ``autonomy_thrash_elevated``
     alert kinds.
  6. ``cli.py`` daily-brief block references
     ``compute_thrash`` (autonomy-overview-history --thrash
     drill hint).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


_THRASH_VERDICTS = {"calm", "elevated", "thrashing"}


@dataclass
class PatternBRViolation:
    invariant: str
    reason: str


@dataclass
class PatternBRReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBRViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBRReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBRViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_br_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBRReport:
    """Verify the thrash detection chain."""
    report = PatternBRReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"
    notify_path = root / "engines" / "_notify.py"

    # 1: compute_thrash works
    try:
        from core.automation.autonomy_overview_thrash import (
            ThrashReport, compute_thrash,
        )
        r = compute_thrash(window_hours=1.0)
        ok = (
            isinstance(r, ThrashReport)
            and hasattr(r, "verdict")
            and hasattr(r, "buckets")
        )
        _check(
            report, "compute_thrash_returns_report",
            ok,
            (
                "compute_thrash did not return a "
                "ThrashReport-shaped object"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "compute_thrash_returns_report",
            False,
            f"compute_thrash raised: {exc!s:.100}",
        )

    # 2: verdict literal
    try:
        from core.automation.autonomy_overview_thrash import (
            compute_thrash,
        )
        v = compute_thrash().verdict
        _check(
            report, "report_verdict_is_valid_literal",
            v in _THRASH_VERDICTS,
            f"unexpected verdict: {v!r}",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "report_verdict_is_valid_literal",
            False, f"raised: {exc!s:.100}",
        )

    # 3: bucket density_label literal
    try:
        from core.automation.autonomy_overview_thrash import (
            ThrashBucket,
        )
        labels = {
            ThrashBucket(0, 1, 0).density_label,
            ThrashBucket(0, 1, 3).density_label,
            ThrashBucket(0, 1, 10).density_label,
        }
        _check(
            report, "bucket_label_is_valid_literal",
            labels <= _THRASH_VERDICTS,
            f"unexpected density labels: {labels}",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "bucket_label_is_valid_literal",
            False, f"raised: {exc!s:.100}",
        )

    # 4: CLI --thrash flag
    _check(
        report, "cli_registers_thrash_flag",
        _file_references(
            cli_path,
            "autonomy_overview_history_p.add_argument",
            '"--thrash"',
        ),
        (
            "cli.py does not register --thrash on "
            "autonomy_overview_history_p"
        ),
    )

    # 5: notify wires both alert kinds
    _check(
        report, "notify_registers_thrash_alerts",
        _file_references(
            notify_path,
            '"autonomy_thrash"',
            '"autonomy_thrash_elevated"',
        ),
        (
            "engines/_notify.py does not register both "
            "autonomy_thrash + autonomy_thrash_elevated"
        ),
    )

    # 6: daily-brief refers to compute_thrash + drill hint
    _check(
        report, "daily_brief_renders_thrash_row",
        _file_references(
            cli_path,
            "compute_thrash",
            "autonomy-overview-history --thrash",
        ),
        (
            "cli.py daily-brief block does not call "
            "compute_thrash or omits the drill hint"
        ),
    )

    return report
