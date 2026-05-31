"""Pattern BA audit: notify alert-kind catalog completeness (W852).

Companion to Pattern V (which checks per-domain
{paused, health_critical} alert kinds are REFERENCED in
``collect_alerts``). Pattern BA adds the inverse check for the
coalesce set: the ``autonomy_kinds`` set inside
``engines/_notify.py``'s coalesce block must mention EXACTLY
the per-domain alert kinds for the current autonomy domain
catalog.

When a new autonomy domain ships, its 2 alert kinds get added
to ``collect_alerts``'s probe code (caught by Pattern V), but
operators sometimes forget to add them to the coalesce set too.
Result: the coalesce path silently misses the new domain's
alerts. Pattern BA catches this.

Implementation: AST-scan _notify.py, locate the
``autonomy_kinds = {...}`` assignment, collect the literal
strings, and compare with the expected set derived from
``DOMAIN_APPLY_FLAGS``.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_NOTIFY_PATH = Path("engines") / "_notify.py"


@dataclass
class PatternBAViolation:
    expected: str
    reason: str


@dataclass
class PatternBAReport:
    expected_kinds: list[str] = field(default_factory=list)
    catalog_kinds: list[str] = field(default_factory=list)
    missing_in_catalog: list[str] = field(default_factory=list)
    extra_in_catalog: list[str] = field(default_factory=list)
    violations: list[PatternBAViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


# W937: system-level alert kinds that legitimately live in
# the coalesce set but are NOT owned by a per-domain probe.
# Adding to this set means the audit will tolerate the kind
# in autonomy_kinds without expecting a corresponding domain.
_SYSTEM_LEVEL_KINDS = {
    # W907 verdict-flip thrash alerts (operator-wide)
    "autonomy_thrash",
    "autonomy_thrash_elevated",
}


def _expected_kinds() -> set[str]:
    """Build (paused, health_critical) pairs per autonomy
    domain. Domain key mappings mirror the per-domain notify
    probe sections (refund + budget aliases live alongside
    the canonical names)."""
    try:
        from core.automation.autonomy_armed import (
            DOMAIN_APPLY_FLAGS,
        )
    except Exception:  # noqa: BLE001
        return set()
    # The notify probe uses a few shortened names where they
    # differ from the canonical domain key. Match those.
    aliases = {
        "customer_support": "refund",
        "marketing": "budget",
    }
    out: set[str] = set()
    for domain in DOMAIN_APPLY_FLAGS:
        prefix = aliases.get(domain, domain)
        out.add(f"{prefix}_paused")
        out.add(f"{prefix}_health_critical")
    # System-level kinds are always expected
    out |= _SYSTEM_LEVEL_KINDS
    return out


def _scan_autonomy_kinds_set(
    path: Path,
) -> set[str] | None:
    """AST-scan _notify.py for ``autonomy_kinds = {...}``.
    Returns the literal string set, or None if not found."""
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
    except Exception:  # noqa: BLE001
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # Targets is autonomy_kinds (single Name assignment)
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id != "autonomy_kinds":
            continue
        # Value should be a Set literal
        if not isinstance(node.value, ast.Set):
            continue
        out: set[str] = set()
        for elt in node.value.elts:
            if (
                isinstance(elt, ast.Constant)
                and isinstance(elt.value, str)
            ):
                out.add(elt.value)
        return out
    return None


def run_pattern_ba_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBAReport:
    """Verify the notify autonomy_kinds set covers every
    autonomy domain's two alert kinds."""
    report = PatternBAReport()
    root = Path(repo_root).resolve()
    path = root / _NOTIFY_PATH
    if not path.exists():
        report.violations.append(PatternBAViolation(
            expected="",
            reason=f"{_NOTIFY_PATH} not found at repo root",
        ))
        return report

    expected = _expected_kinds()
    catalog = _scan_autonomy_kinds_set(path)
    report.expected_kinds = sorted(expected)
    if catalog is None:
        report.violations.append(PatternBAViolation(
            expected=",".join(sorted(expected)),
            reason=(
                "_notify.py has no `autonomy_kinds = {...}` "
                "Set literal at top level of collect_alerts"
            ),
        ))
        return report
    report.catalog_kinds = sorted(catalog)
    missing = expected - catalog
    extra = catalog - expected
    report.missing_in_catalog = sorted(missing)
    report.extra_in_catalog = sorted(extra)
    for k in sorted(missing):
        report.violations.append(PatternBAViolation(
            expected=k,
            reason=(
                "kind expected by an autonomy domain but not "
                "in notify autonomy_kinds set -- coalesce path "
                "will silently miss it"
            ),
        ))
    for k in sorted(extra):
        report.violations.append(PatternBAViolation(
            expected=k,
            reason=(
                "kind in notify autonomy_kinds set but not "
                "owned by any active domain -- stale entry, "
                "likely a removed domain"
            ),
        ))
    return report
