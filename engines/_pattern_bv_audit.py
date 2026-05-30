"""Pattern BV audit: thrash guardrail per-applier wireup (W918).

Strict variant: every minter file under the Phase 6/7 wireup
roster must call ``should_block_thrashing_store`` in its
main applier function.

The roster is the 6 minters identified during Phase 6/7
(``[[project-phase-6-substrate]]``); when a new minter
joins the wireup, it gets added to ``_WIREUP_ROSTER``.

Invariants:

  1. Every roster entry has a writer file that exists.
  2. Every writer file references ``should_block_thrashing_store``
     at least once (loose AST-friendly text grep).
  3. Every writer file calls ``explain_thrash_block`` (paired
     with the block call so the writeback's error field
     carries the canonical token).

Pattern BV's roster is intentionally small (1 wired today,
5 pending). Engines that haven't wired yet appear as
violations so operators can track progress; the wireup is
not the audit's job, but visibility is.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# (engine_name, path_relative_to_repo_root)
_WIREUP_ROSTER: tuple[tuple[str, str], ...] = (
    ("loyalty", "engines/loyalty/discount_minter.py"),
    # Pending (intentionally listed so audit surfaces them):
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
    (
        "affiliate",
        "engines/affiliate/commission_payer.py",
    ),
    (
        "product_lifecycle",
        "engines/product_lifecycle/lifecycle_applier.py",
    ),
)


@dataclass
class PatternBVViolation:
    invariant: str
    reason: str
    engine: str = ""


@dataclass
class PatternBVReport:
    invariants_checked: list[str] = field(default_factory=list)
    clean_invariants: list[str] = field(default_factory=list)
    violations: list[PatternBVViolation] = field(
        default_factory=list,
    )
    wired_count: int = 0
    pending_count: int = 0

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _file_references(path: Path, *symbols: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return False
    return all(s in text for s in symbols)


def run_pattern_bv_audit(
    *,
    repo_root: str | Path = ".",
    strict: bool = True,
) -> PatternBVReport:
    """Verify the W917+ thrash guardrail wireup roster.

    Default is ``strict=True`` after Phase 175 closed the
    roster (6/6 wired). Future roster additions add as
    ``(engine, path)`` tuples and immediately gate; the loose
    mode (``strict=False``) is preserved for ergonomic
    progress queries during partial roll-outs.
    """
    report = PatternBVReport()
    root = Path(repo_root).resolve()

    for engine, rel in _WIREUP_ROSTER:
        path = root / rel
        invariant_name = f"writer_exists_{engine}"
        report.invariants_checked.append(invariant_name)
        if not path.exists():
            report.violations.append(PatternBVViolation(
                invariant=invariant_name,
                reason=f"writer not found at {rel}",
                engine=engine,
            ))
            continue
        report.clean_invariants.append(invariant_name)

        # block + explain references (strict path)
        block_inv = f"block_call_{engine}"
        report.invariants_checked.append(block_inv)
        has_block = _file_references(
            path, "should_block_thrashing_store",
        )
        if has_block:
            report.clean_invariants.append(block_inv)
            report.wired_count += 1
        else:
            report.pending_count += 1
            if strict:
                report.violations.append(PatternBVViolation(
                    invariant=block_inv,
                    reason=(
                        "missing should_block_thrashing_store "
                        "call"
                    ),
                    engine=engine,
                ))

        explain_inv = f"explain_call_{engine}"
        report.invariants_checked.append(explain_inv)
        has_explain = _file_references(
            path, "explain_thrash_block",
        )
        if has_explain:
            report.clean_invariants.append(explain_inv)
        else:
            if strict and has_block:
                # block without explain is a real problem
                report.violations.append(PatternBVViolation(
                    invariant=explain_inv,
                    reason=(
                        "block call present but "
                        "explain_thrash_block missing"
                    ),
                    engine=engine,
                ))

    return report
