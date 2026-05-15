"""Pattern J audit -- guards against unrecorded writes to the
autonomous learning singletons (MemoryIntelligence,
DataArchitecture, LearningLoop) from non-recorder modules.

CLAUDE.md Pattern J documents the bug class: any module that
imports one of those singletons and writes during normal
operation will pollute on-disk SQLite the moment a test runs
the path. The failure-intelligence pipeline then auto-generates
bogus avoidance rules from test fixtures.

The canonical fix is ``_writeback_recorder.py`` which short-
circuits under ``PYTEST_CURRENT_TEST``. New modules that write
directly to these singletons need either:

  1. To delegate through ``record_writeback`` (preferred), OR
  2. To declare their own ``_is_test_environment`` guard the
     audit can recognise.

This module surfaces every call to a known WRITE method
(MemoryIntelligence.create_from_decision /record_failure,
DataArchitecture.record_action /attach_result, LearningLoop.learn)
across engines/ + core/, and classifies each into:

  - **recorder**: the legitimate Phase 8 bridge (whitelisted).
  - **guarded**: a non-recorder module that ALSO defines an
    ``_is_test_environment`` function -- presumed safe.
  - **unguarded**: a write-site with no recognised guard ->
    PATTERN J VIOLATION.

A non-empty ``unguarded`` list fails the audit (and the CI gate
that runs it). Each unguarded site needs a per-PR fix: either
route through ``_writeback_recorder`` or add the test gate.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.logger import get_logger

logger = get_logger("engines._pattern_j_audit")


# WRITE method names we scan for. Method names alone are too
# noisy (``attach_result`` is also the ApprovalQueue method;
# ``learn`` exists on many objects), so we ALSO require the
# file to import one of the singleton classes -- the AND of
# both signals is what makes the audit precise.
_WRITE_METHOD_NAMES = frozenset({
    "create_from_decision",
    "record_failure",
    "record_action",
    "attach_result",
    "learn",
})

# Singleton class names that, when imported by a module, mean
# "this module *might* write to the learning loop." Combined
# with the method-name match, this filters out the bulk of the
# Python-overloaded false positives.
_TARGET_IMPORTS = frozenset({
    "MemoryIntelligence",
    "DataArchitecture",
    "LearningLoop",
})

# Modules where writes are LEGITIMATE -- either:
#   * The canonical Phase 8 bridge that already gates on
#     PYTEST_CURRENT_TEST (``_writeback_recorder.py``).
#   * The autonomous-cycle runner, which is not exercised by
#     unit tests directly (no test calls ``AutonomousController.
#     run_cycle()``); integration tests use a different code
#     path that doesn't call these singletons.
# Whitelisted by RELATIVE PATH (POSIX) so a same-named file in
# a different directory doesn't accidentally inherit the
# whitelist. Adding a path here is a deliberate operator
# decision -- new write-sites that don't fit either category
# should add the ``_is_test_environment`` guard instead.
_RECORDER_WHITELIST = frozenset({
    "engines/_writeback_recorder.py",
    "core/autonomous/controller.py",
})


@dataclass(frozen=True)
class WriteSite:
    """One call to a known WRITE method."""

    file: str           # relative path
    lineno: int
    method: str         # which WRITE method
    receiver_expr: str  # caller-visible repr of the receiver
    module_path: str    # full path for grouping


@dataclass(frozen=True)
class PatternJReport:
    recorder_sites: list[WriteSite] = field(default_factory=list)
    guarded_sites: list[WriteSite] = field(default_factory=list)
    unguarded_sites: list[WriteSite] = field(default_factory=list)
    scanned_modules: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.unguarded_sites)


def _module_has_test_env_guard(tree: ast.AST) -> bool:
    """True iff the module defines an ``_is_test_environment``
    function (the recognised Pattern J guard idiom)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name == "_is_test_environment":
                return True
    return False


def _module_imports_target(tree: ast.AST) -> bool:
    """True iff the module imports one of the singleton classes
    in ``_TARGET_IMPORTS``. Two patterns recognised:
      - ``from core.memory.intelligence import MemoryIntelligence``
      - ``import core.memory.intelligence as mi`` (alias-based;
        we approximate by checking module names containing the
        sub-string)
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _TARGET_IMPORTS:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # Approximation: module path mentions the
                # singleton's home module
                if (
                    "memory.intelligence" in alias.name
                    or "data.architecture" in alias.name
                    or "learning_loop" in alias.name
                ):
                    return True
    return False


def _receiver_repr(call: ast.Call) -> str:
    """Best-effort string repr of the call's receiver for the
    audit report. Doesn't try to be complete -- just enough to
    eyeball whether the call is suspicious."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return "<?>"
    try:
        return ast.unparse(func.value)
    except Exception:  # noqa: BLE001
        return "<?>"


def _collect_writes(
    py_path: Path,
    base: Path,
) -> tuple[list[WriteSite], bool]:
    """Walk one file's AST. Returns (write_sites, has_guard)."""
    sites: list[WriteSite] = []
    try:
        src = py_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("could not read %s: %s", py_path, exc)
        return [], False
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as exc:
        logger.debug("syntax error in %s: %s", py_path, exc)
        return [], False

    has_guard = _module_has_test_env_guard(tree)
    # Skip files that don't import a target singleton -- they
    # can't be writing to one (a `.attach_result()` call on
    # ApprovalQueue is not Pattern J).
    if not _module_imports_target(tree):
        return [], has_guard

    rel = py_path.relative_to(base).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _WRITE_METHOD_NAMES:
            continue
        sites.append(WriteSite(
            file=rel,
            lineno=node.lineno,
            method=func.attr,
            receiver_expr=_receiver_repr(node),
            module_path=str(py_path),
        ))
    return sites, has_guard


def _is_recorder(rel_path: str) -> bool:
    """Whitelist check by RELATIVE POSIX path so a same-named
    file in a different directory doesn't inherit the
    whitelist."""
    return rel_path in _RECORDER_WHITELIST


def audit_pattern_j(
    *,
    roots: Iterable[Path | str] | None = None,
) -> PatternJReport:
    """Scan the configured roots for WRITE-method call sites,
    classify into recorder / guarded / unguarded.

    Args:
        roots: Iterable of directory paths to scan. Defaults to
            ``engines/`` and ``core/`` next to this module.
    """
    if roots is None:
        here = Path(__file__).resolve().parent
        roots = [here, here.parent / "core"]
    paths = [Path(r) for r in roots]

    recorder: list[WriteSite] = []
    guarded: list[WriteSite] = []
    unguarded: list[WriteSite] = []
    scanned = 0
    for root in paths:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            scanned += 1
            sites, has_guard = _collect_writes(py_path, root.parent)
            if not sites:
                continue
            rel = py_path.relative_to(root.parent).as_posix()
            if _is_recorder(rel):
                recorder.extend(sites)
            elif has_guard:
                guarded.extend(sites)
            else:
                unguarded.extend(sites)
    return PatternJReport(
        recorder_sites=recorder,
        guarded_sites=guarded,
        unguarded_sites=unguarded,
        scanned_modules=scanned,
    )
