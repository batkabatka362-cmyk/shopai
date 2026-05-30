"""Pattern BH audit: per-store cooldown chain (W877).

Verifies the W875 + W876 per-store cooldown scoping reaches
every link in the chain.

Invariants:

  1. ``recent_disarms`` accepts ``store_id`` kwarg.
  2. ``last_disarm_at`` accepts ``store_id`` kwarg.
  3. ``autonomy_armed.py`` references ``last_disarm_at(`` AND
     forwards ``store_id=`` -- closing the loop so per-store
     arm queries per-store cooldown.
  4. CLI ``autonomy-disarm-history`` registers a --store flag.

If any link is broken, a store-7 disarm either blocks ALL
stores' re-arm (over-blocking) OR has no effect at all
(under-blocking).

Companion to Pattern BC (cooldown chain) but scoped to the
per-store layer added in W875/W876.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBHViolation:
    invariant: str
    reason: str


@dataclass
class PatternBHReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBHViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBHReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBHViolation(
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


def run_pattern_bh_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBHReport:
    """Verify per-store cooldown chain is fully wired."""
    report = PatternBHReport()
    root = Path(repo_root).resolve()

    # 1-2: function signatures
    try:
        from core.automation.substrate_fire_disarm_log import (  # noqa
            last_disarm_at, recent_disarms,
        )
        _check(
            report, "recent_disarms_accepts_store_id",
            _has_param(recent_disarms, "store_id"),
            "recent_disarms does not accept store_id kwarg",
        )
        _check(
            report, "last_disarm_at_accepts_store_id",
            _has_param(last_disarm_at, "store_id"),
            "last_disarm_at does not accept store_id kwarg",
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBHViolation(
            invariant="disarm_log_import",
            reason=f"import failed: {exc!s:.150}",
        ))

    # 3: autonomy_armed forwards store_id to last_disarm_at
    armed_path = (
        root / "core" / "automation" / "autonomy_armed.py"
    )
    _check(
        report, "arm_forwards_store_id_to_last_disarm_at",
        _file_references(
            armed_path,
            "last_disarm_at",
            "store_id=",
        ),
        (
            "autonomy_armed.arm does not forward store_id "
            "to last_disarm_at -- per-store cooldown ignored"
        ),
    )

    # 4: CLI disarm-history has --store flag
    cli_path = root / "cli.py"
    _check(
        report, "cli_disarm_history_has_store_flag",
        _file_references(
            cli_path,
            "autonomy_disarm_hist_p.add_argument",
            '"--store"',
        ),
        (
            "cli.py autonomy_disarm_hist_p does not register "
            "--store flag -- operator can't filter per-store"
        ),
    )

    return report
