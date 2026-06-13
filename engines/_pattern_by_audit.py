"""Pattern BY audit: thrash block log chain (W933).

Companion to [[pattern-bw]]/[[pattern-bx]]. BY guards the
W930-932 read-side substrate that lets operators query
blocked writebacks fast.

Invariants:

  1. ``thrash_block_log`` exports the canonical 3 callables
     (``record_block`` + ``recent_blocks`` + ``block_count``).
  2. ``BlockEntry`` exposes the 6 expected fields.
  3. ``log_thrash_block`` exported by ``engines._agi_context``.
  4. CLI ``thrash-blocks`` subparser registered.
  5. All 6 W917-923 wired appliers call ``log_thrash_block``
     (parity check with Pattern BV's roster).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)


_EXPECTED_ENTRY_FIELDS = {
    "blocked_at", "engine", "action_type",
    "capability", "store_id", "reason",
}

# Same as BV's roster
_WIREUP_ROSTER = (
    ("loyalty", "engines/loyalty/discount_minter.py"),
    (
        "discount_strategy",
        "engines/discount_strategy/discount_minter.py",
    ),
    (
        "dynamic_pricing",
        "engines/dynamic_pricing/price_applier.py",
    ),
    (
        "tag_management",
        "engines/tag_management/tag_applier.py",
    ),
    ("affiliate", "engines/affiliate/commission_payer.py"),
    (
        "product_lifecycle",
        "engines/product_lifecycle/lifecycle_applier.py",
    ),
)


@dataclass
class PatternBYViolation:
    invariant: str
    reason: str


@dataclass
class PatternBYReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBYViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _check(
    report: PatternBYReport,
    name: str,
    ok: bool,
    why: str = "",
) -> None:
    report.invariants_checked.append(name)
    if ok:
        report.clean_invariants.append(name)
    else:
        report.violations.append(PatternBYViolation(
            invariant=name, reason=why,
        ))


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_by_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternBYReport:
    """Verify the W930-932 thrash block log chain."""
    report = PatternBYReport()
    root = Path(repo_root).resolve()
    cli_path = root / "cli.py"

    # 1: callables exported
    try:
        from core.automation import thrash_block_log as _t
        missing = [
            n for n in (
                "record_block", "recent_blocks", "block_count",
            )
            if not callable(getattr(_t, n, None))
        ]
        _check(
            report, "module_exports_helpers",
            not missing,
            f"missing callables: {missing}",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "module_exports_helpers", False,
            f"import raised: {exc!s:.100}",
        )

    # 2: BlockEntry shape
    try:
        from core.automation.thrash_block_log import BlockEntry
        names = {f.name for f in fields(BlockEntry)}
        missing = _EXPECTED_ENTRY_FIELDS - names
        _check(
            report, "block_entry_has_all_fields",
            not missing,
            f"BlockEntry missing fields: {sorted(missing)}",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "block_entry_has_all_fields", False,
            f"raised: {exc!s:.100}",
        )

    # 3: log_thrash_block exported
    try:
        from engines._agi_context import log_thrash_block
        _check(
            report, "log_thrash_block_exported",
            callable(log_thrash_block),
            "log_thrash_block not callable",
        )
    except Exception as exc:  # noqa: BLE001
        _check(
            report, "log_thrash_block_exported", False,
            f"raised: {exc!s:.100}",
        )

    # 4: CLI subparser
    _check(
        report, "cli_registers_thrash_blocks_subparser",
        _file_references(
            cli_path,
            'thrash_blocks_p = sub.add_parser',
        ),
        "cli.py does not register thrash_blocks_p subparser",
    )

    # 5: all 6 appliers call log_thrash_block
    for engine, rel in _WIREUP_ROSTER:
        inv = f"applier_calls_log_thrash_block_{engine}"
        path = root / rel
        ok = _file_references(path, "log_thrash_block")
        _check(
            report, inv, ok,
            (
                f"{rel} does not call log_thrash_block"
            ),
        )

    return report
