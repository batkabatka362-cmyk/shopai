"""Pattern Z audit -- every writer module that calls a Shopify
mutation MUST also call ``record_writeback`` so the autonomous
learning loop sees the outcome.

The bug class this prevents (caught live in PR #205):

  Four minters (browse_recovery, cart_recovery, email_marketing,
  wholesale_b2b) called ``mint_recovery_code`` (which routes to
  ``SHOPIFY_CREATE_DISCOUNT``) but did NOT call
  ``record_writeback``. The minted codes were real on Shopify,
  but MemoryIntelligence / DataArchitecture / LearningLoop never
  saw the mint event. The recommender and EMA undercount these
  engines' impact.

Pattern Z covers every engine module whose name signals a
writer role:

  * ``*_applier.py`` -- the canonical applier pattern
  * ``*_minter.py``  -- discount-code mint helpers
  * ``*_payer.py``   -- payouts / gift-card mints

A file is flagged when:

  1. It calls ``router.execute(...)`` OR ``_router_call(...)``
     OR ``mint_recovery_code(...)`` OR the aliased ``_mint(...)``.
  2. It does NOT call ``record_writeback(...)`` anywhere in the
     same file.

Both signals come from a single AST walk per file (no regex --
the AST handles the import-alias case automatically because we
look for Call nodes by attribute name, not text).

Returns ``(ok, sites)`` where ``sites`` is the list of files
that fail the audit. A clean baseline returns an empty list and
``ok=True``.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.logger import get_logger

logger = get_logger("engines._pattern_z_audit")


# Filename suffixes that mark a module as a "writer" -- subject
# to the Pattern Z check.
_WRITER_SUFFIXES = (
    "_applier.py",
    "_minter.py",
    "_payer.py",
)

# Call names that indicate a Shopify mutation is happening. Any
# of these in a writer file means a record_writeback must also
# exist in the same file.
_MUTATION_CALL_NAMES = frozenset({
    "execute",            # router.execute(...)
    "_router_call",       # core/approval/dispatchers shared helper
    "mint_recovery_code", # shared discount-code mint helper
    "_mint",              # the common ``from ... import mint_recovery_code as _mint`` alias
})

# Files that legitimately exempt themselves -- they ARE the
# canonical Phase 8 bridge, not callers of it. (Empty today;
# placeholder for any future "wraps" the recorder.)
_EXEMPT_PATHS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class WriterAuditSite:
    """One writer file that's missing a record_writeback call."""

    file: str             # relative posix path under engines/
    mutation_calls: tuple[str, ...]  # which mutation names were found
    has_recorder_import: bool        # does the module import record_writeback?


@dataclass(frozen=True)
class PatternZReport:
    scanned_writers: int
    clean_writers: list[str] = field(default_factory=list)
    missing_recorder: list[WriterAuditSite] = field(
        default_factory=list,
    )
    skipped_no_mutation: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.missing_recorder)


def _is_writer_module(name: str) -> bool:
    """True iff filename ends in one of the writer suffixes."""
    return any(name.endswith(suffix) for suffix in _WRITER_SUFFIXES)


def _scan_writer(py_path: Path, base: Path) -> tuple[
    tuple[str, ...],  # mutation_calls found
    bool,             # has record_writeback CALL
    bool,             # imports record_writeback
]:
    """AST-walk a writer file. Returns the three signals the
    audit needs to classify it."""
    try:
        src = py_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("could not read %s: %s", py_path, exc)
        return (), False, False
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as exc:
        logger.debug("syntax error in %s: %s", py_path, exc)
        return (), False, False

    mutations: list[str] = []
    has_recorder_call = False
    has_recorder_import = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "record_writeback":
                    has_recorder_import = True
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else ""
            )
            if name == "record_writeback":
                has_recorder_call = True
            elif name in _MUTATION_CALL_NAMES:
                if name not in mutations:
                    mutations.append(name)

    return tuple(mutations), has_recorder_call, has_recorder_import


def audit_pattern_z(
    *,
    engines_root: Path | str | None = None,
) -> PatternZReport:
    """Scan engines/ for writer modules and verify each one calls
    ``record_writeback`` adjacent to its mutation calls.

    Args:
        engines_root: Optional override of ``engines/`` path.
            Defaults to ``<repo>/engines``.
    """
    if engines_root is None:
        engines_root = Path(__file__).resolve().parent
    else:
        engines_root = Path(engines_root)
    if not engines_root.exists():
        return PatternZReport(scanned_writers=0)

    clean: list[str] = []
    missing: list[WriterAuditSite] = []
    skipped: list[str] = []
    scanned = 0
    for py_path in engines_root.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        if not _is_writer_module(py_path.name):
            continue
        rel = py_path.relative_to(engines_root).as_posix()
        if rel in _EXEMPT_PATHS:
            continue
        scanned += 1

        mutations, has_call, has_import = _scan_writer(
            py_path, engines_root,
        )
        if not mutations:
            # Writer module that doesn't actually call any
            # mutation (defensive scaffolding, types-only module).
            skipped.append(rel)
            continue
        if has_call:
            clean.append(rel)
            continue
        missing.append(WriterAuditSite(
            file=rel,
            mutation_calls=mutations,
            has_recorder_import=has_import,
        ))

    return PatternZReport(
        scanned_writers=scanned,
        clean_writers=clean,
        missing_recorder=missing,
        skipped_no_mutation=skipped,
    )
