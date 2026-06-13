"""Pattern BK audit: autonomy-discover --store plumbing (W886).

Verifies the W885 ``autonomy-discover --store`` flag actually
plumbs the value through to ``payload_discoverer.discover()``.

Invariants:

  1. CLI ``autonomy_discover_p`` registers ``--store`` flag.
  2. CLI handler ``_cmd_autonomy_discover`` references
     ``store_id=`` (the kwarg passed to discover()).
  3. ``payload_discoverer.discover`` accepts ``store_id`` kwarg
     (already audited at the substrate level but worth a
     belt-and-braces check here too).

Companion to Pattern BG (W874) which audits the read-side
fleet of autonomy CLIs. BK specifically targets autonomy-
discover because it's the operator's per-store sanity-check
loop -- if the flag doesn't plumb, the operator can't validate
their per-store env tuning.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBKViolation:
    invariant: str
    reason: str


@dataclass
class PatternBKReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBKViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBKReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBKViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bk_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBKReport:
    """Verify autonomy-discover --store plumbing."""
    report = PatternBKReport()
    root = Path(repo_root).resolve()

    cli_path = root / "cli.py"
    _check(
        report, "cli_discover_has_store_flag",
        _file_references(
            cli_path,
            "autonomy_discover_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_discover_p does not register "
            "--store flag"
        ),
    )
    _check(
        report, "cli_discover_plumbs_store_id",
        _file_references(
            cli_path, "_cmd_autonomy_discover", "store_id=",
        ),
        (
            "cli.py _cmd_autonomy_discover does not pass "
            "store_id= to discover() -- --store flag silently "
            "ignored"
        ),
    )

    try:
        from core.automation.payload_discoverer import (
            discover,
        )
        sig = inspect.signature(discover)
        _check(
            report, "discover_accepts_store_id",
            "store_id" in sig.parameters,
            "discover() does not accept store_id kwarg",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBKViolation(
            invariant="discover_import",
            reason=f"import failed: {exc!s:.150}",
        ))

    return report
