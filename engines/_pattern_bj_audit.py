"""Pattern BJ audit: every discoverer adopts the env helper (W884).

Strict variant of Pattern BI. Where BI just needed at least
ONE discoverer to adopt the W879 helper, BJ requires EVERY
discoverer in ``core/automation/discoverers/`` to reference
``discoverer_env`` or the ``resolve_int``/``resolve_float``
helpers.

Rationale: now that all 8 discoverers ship per-store env
overrides via the W879 helper, future scaffolded discoverers
should default to the same pattern. BJ catches the regression
class "operator-added discoverer with hard-coded env reads
that bypass the per-store layer".

Per-discoverer text-grep for ``discoverer_env`` or
``resolve_int``/``resolve_float``. Light enough that the
audit's clean count maps 1:1 to migrated discoverers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


_HELPER_TOKENS = (
    "discoverer_env",
    "resolve_int",
    "resolve_float",
)


@dataclass
class PatternBJViolation:
    discoverer: str
    reason: str


@dataclass
class PatternBJReport:
    discoverers_scanned: list[str] = field(default_factory=list)
    clean_discoverers: list[str] = field(default_factory=list)
    violations: list[PatternBJViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def run_pattern_bj_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBJReport:
    """Verify every discoverer adopts the per-store env helper."""
    report = PatternBJReport()
    root = Path(repo_root).resolve()
    d = root / "core" / "automation" / "discoverers"
    if not d.is_dir():
        report.violations.append(PatternBJViolation(
            discoverer="",
            reason=(
                f"discoverers directory not found at "
                f"{d.relative_to(root).as_posix()}"
            ),
        ))
        return report

    for f in sorted(d.glob("*.py")):
        if f.name == "__init__.py":
            continue
        name = f.stem
        report.discoverers_scanned.append(name)
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            report.violations.append(PatternBJViolation(
                discoverer=name,
                reason="file unreadable",
            ))
            continue
        if any(tok in text for tok in _HELPER_TOKENS):
            report.clean_discoverers.append(name)
        else:
            report.violations.append(PatternBJViolation(
                discoverer=name,
                reason=(
                    "no reference to discoverer_env / "
                    "resolve_int / resolve_float -- discoverer "
                    "bypasses the per-store env layer"
                ),
            ))

    return report
