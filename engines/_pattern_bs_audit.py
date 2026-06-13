"""Pattern BS audit: empire+per-store thrash surfaces (W911).

Companion to [[pattern-br]]. BR guards the W904-907 thrash
substrate; BS guards the W910 empire + per-store surfacing.
Operators rely on the empire dashboard to surface elevated /
thrashing verdicts inline, and on the per-store --store flag
on autonomy-overview-history --thrash to drill into a
specific store.

Invariants:

  1. ``compute_thrash`` accepts ``store_id`` kwarg.
  2. ``ThrashReport.store_id`` echo-back honored.
  3. ``cli.py`` empire dashboard builds a ``thrash_block`` +
     emits it on the JSON envelope.
  4. ``cli.py`` empire dashboard renders an inline thrash
     row reference (drill hint to
     ``autonomy-overview-history --thrash``).
  5. ``cli.py`` history CLI plumbs ``store`` into the thrash
     view (both compute_thrash call site + scope label).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBSViolation:
    invariant: str
    reason: str


@dataclass
class PatternBSReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBSViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBSReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBSViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bs_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBSReport:
    """Verify the empire + per-store thrash surfaces."""
    report = PatternBSReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: compute_thrash accepts store_id
    try:
        import inspect
        from core.automation.autonomy_overview_thrash import (
            compute_thrash,
        )
        sig = inspect.signature(compute_thrash)
        _check(
            report, "compute_thrash_accepts_store_id",
            "store_id" in sig.parameters,
            "compute_thrash() missing store_id kwarg",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "compute_thrash_accepts_store_id",
            False, f"raised: {exc!s:.100}",
        )

    # 2: ThrashReport.store_id echo
    try:
        from core.automation.autonomy_overview_thrash import (
            compute_thrash,
        )
        rep = compute_thrash(store_id="probe-store")
        _check(
            report, "report_store_id_echoes_back",
            rep.store_id == "probe-store",
            (
                f"compute_thrash(store_id=...) did not echo: "
                f"got {rep.store_id!r}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "report_store_id_echoes_back",
            False, f"raised: {exc!s:.100}",
        )

    # 3: empire builds thrash_block + emits to JSON
    _check(
        report, "empire_builds_thrash_block",
        _file_references(
            cli_path,
            "thrash_block",
            '"thrash": thrash_block',
        ),
        (
            "cli.py empire dashboard does not build/emit "
            "thrash_block"
        ),
    )

    # 4: empire renders inline drill hint
    _check(
        report, "empire_renders_thrash_drill_hint",
        _file_references(
            cli_path,
            "thrash_block.get(\"verdict\")",
            "autonomy-overview-history "
            "--thrash",
        ),
        (
            "cli.py empire does not render the thrash "
            "inline row + drill hint"
        ),
    )

    # 5: history CLI plumbs store into thrash view.
    # Look for compute_thrash(...) called with store_id=
    # nearby in the file.
    _check(
        report, "history_cli_threads_store_into_thrash",
        _file_references(
            cli_path,
            "thrash_view",
            "store_id=store or None",
        ),
        (
            "cli.py history CLI does not thread store into "
            "compute_thrash"
        ),
    )

    return report
