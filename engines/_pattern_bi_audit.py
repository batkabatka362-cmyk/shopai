"""Pattern BI audit: per-store discoverer env helper (W880).

Verifies the W879 per-store discoverer env layer is wired:

  1. ``discoverer_env.resolve_int`` is callable.
  2. ``discoverer_env.resolve_float`` is callable.
  3. ``_normalise`` correctly mangles store IDs (live
     spot-check: ``store-7`` -> ``STORE_7``).
  4. At least one production discoverer references the helper
     (otherwise the substrate is dead weight).

This is a substrate-availability audit. Pattern BI is light
on coverage by design -- per-discoverer Pattern T-style
catalogs would be heavy + we don't want operators to be
forced to migrate every discoverer at once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatternBIViolation:
    invariant: str
    reason: str


@dataclass
class PatternBIReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBIViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBIReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBIViolation(
            invariant=name, reason=why,
        ))


def run_pattern_bi_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBIReport:
    """Verify the per-store discoverer env layer is wired."""
    report = PatternBIReport()
    root = Path(repo_root).resolve()

    # 1-2: callables
    try:
        from core.automation.discoverer_env import (
            _normalise, resolve_float, resolve_int,
        )
        _check(
            report, "resolve_int_callable",
            callable(resolve_int),
            "resolve_int not callable",
        )
        _check(
            report, "resolve_float_callable",
            callable(resolve_float),
            "resolve_float not callable",
        )
        # 3: normalisation behaviour spot-check
        _check(
            report, "store_id_normalises_correctly",
            _normalise("store-7") == "STORE_7",
            (
                "_normalise('store-7') != 'STORE_7' -- per-"
                "store env naming will drift from convention"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternBIViolation(
            invariant="discoverer_env_import",
            reason=f"import failed: {exc!s:.150}",
        ))
        return report

    # 4: at least one discoverer adopts the helper
    discoverers_dir = (
        root / "core" / "automation" / "discoverers"
    )
    adopted = False
    if discoverers_dir.is_dir():
        for f in discoverers_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if "discoverer_env" in text or "resolve_int" in text:
                adopted = True
                break
    _check(
        report, "at_least_one_discoverer_adopts_helper",
        adopted,
        (
            "no discoverer in core/automation/discoverers "
            "references discoverer_env -- helper is dead "
            "weight"
        ),
    )

    return report
