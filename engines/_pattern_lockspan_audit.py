"""Pattern Lock-Span audit -- detect load+modify+save without spanning lock.

CLAUDE.md documents the lost-update race class repeatedly caught
across W962-15 to W962-46. The pattern (29 modules retrofitted):

  def record_X(event):
      rows = _load()       # 1. read state
      rows.append(event)   # 2. modify
      _save(rows)          # 3. write back

When two threads / processes run record_X concurrently:
  Thread A: rows = [a, b]   # _load returns 2 items
  Thread A: rows.append(x)  # in memory: [a, b, x]
  Thread B: rows = [a, b]   # _load returns 2 items (A hasn't saved yet)
  Thread B: rows.append(y)  # in memory: [a, b, y]
  Thread A: _save([a, b, x])
  Thread B: _save([a, b, y])  # X is LOST

The correct pattern:
  with _LOCK:
      rows = _load()
      rows.append(event)
      _save(rows)

The audit walks modules that have BOTH _load and _save (or
load_X/save_X variants) and checks each function for:
  1. The function contains a call to _load (or load_X)
  2. The function contains a call to _save (or save_X)
  3. The function does NOT hold a Lock/RLock spanning both calls

False positives include:
  - Pure-read functions (have _load but no _save)
  - Setup/init functions (different semantics)
  - Class methods where the lock is on self

The audit ALLOWS:
  - Functions wrapped in `with self._lock` / `with _LOCK` / `with X.acquire`
  - Functions decorated with @_locked or similar
  - Functions in modules where every read+write goes through a
    single threaded queue (rare)

Heuristic: if a function calls both _load_<X>() AND _save_<X>()
(or load/save variants) WITHOUT a `with .*_lock` or `with _LOCK`
in the same function body, flag it.

This is necessarily heuristic; the audit is ADVISORY (does NOT
fail CI). Surfaces candidates for human triage.
"""
from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Function-name suffixes that indicate "read state from disk":
_LOAD_NAMES = (
    "_load", "_load_raw", "_load_state", "_load_history",
    "_load_events", "_load_all", "load_log", "load_state",
)

# Function-name suffixes that indicate "write state to disk":
_SAVE_NAMES = (
    "_save", "_save_raw", "_save_state", "_save_history",
    "_save_events", "_save_all", "save_log", "save_state",
    "_atomic_write", "_write_raw", "_write",
)

# Patterns we accept as "the function holds a lock":
_LOCK_NAMES = (
    "_LOCK", "_lock", "_state_lock", "_history_lock",
    "_path_lock", "_seq_lock", "_locks_mutex",
    "_BUS_LOCK", "_HISTORY_LOCK", "_SNAPSHOT_LOCK",
    "_NOTIFY_LOCK", "_PATH_LOCKS",
)


@dataclass(frozen=True)
class LockSpanViolation:
    """One function that does load+save without a spanning lock."""

    file: str
    function: str
    lineno: int
    load_call: str
    save_call: str
    description: str


@dataclass(frozen=True)
class LockSpanReport:
    """Aggregated Pattern Lock-Span audit result."""

    violations: tuple[LockSpanViolation, ...]
    scanned_files: int
    scanned_functions: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _is_lock_ctx(node: ast.With) -> bool:
    """True iff this `with` block looks like a lock acquisition."""
    for item in node.items:
        ctx = item.context_expr
        # `with _LOCK:` — Name
        if isinstance(ctx, ast.Name):
            if any(n in ctx.id for n in _LOCK_NAMES):
                return True
        # `with self._lock:` — Attribute
        elif isinstance(ctx, ast.Attribute):
            if any(n in ctx.attr for n in _LOCK_NAMES):
                return True
        # `with _LOCK.acquire():` — Call
        elif isinstance(ctx, ast.Call):
            inner = ctx.func
            if isinstance(inner, ast.Attribute):
                if (
                    inner.attr == "acquire"
                    and isinstance(inner.value, (ast.Name, ast.Attribute))
                ):
                    return True
            elif isinstance(inner, ast.Name):
                if any(n in inner.id for n in _LOCK_NAMES):
                    return True
        # `with path_lock(p):` — explicit lock helper call
        elif isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Name):
            if "lock" in ctx.func.id.lower():
                return True
    return False


def _walk_with_lock_check(
    body: list[ast.stmt],
    in_lock: bool = False,
) -> tuple[bool, bool]:
    """Walk a function body and return (has_load_call, has_save_call_unlocked).

    Reports True for has_save_call_unlocked only if the call is
    OUTSIDE every with-lock block. The walker descends into
    branches (if/else/try/loop) so lock coverage in one path
    doesn't excuse uncovered work in another.
    """
    has_load = False
    has_save_unlocked = False
    for stmt in body:
        if isinstance(stmt, ast.With):
            entered_lock = in_lock or _is_lock_ctx(stmt)
            sub_load, sub_save = _walk_with_lock_check(
                stmt.body, entered_lock,
            )
            has_load = has_load or sub_load
            has_save_unlocked = has_save_unlocked or sub_save
        elif isinstance(stmt, (ast.If, ast.Try, ast.For, ast.While)):
            sub_load, sub_save = _walk_with_lock_check(
                stmt.body, in_lock,
            )
            has_load = has_load or sub_load
            has_save_unlocked = has_save_unlocked or sub_save
            # Also walk else/finally/handlers
            for branch in (
                getattr(stmt, "orelse", None) or [],
                getattr(stmt, "finalbody", None) or [],
            ):
                if branch:
                    sub_load2, sub_save2 = _walk_with_lock_check(
                        branch, in_lock,
                    )
                    has_load = has_load or sub_load2
                    has_save_unlocked = has_save_unlocked or sub_save2
            for handler in getattr(stmt, "handlers", []) or []:
                sub_load3, sub_save3 = _walk_with_lock_check(
                    handler.body, in_lock,
                )
                has_load = has_load or sub_load3
                has_save_unlocked = has_save_unlocked or sub_save3
        else:
            # Check this statement for load / save calls
            for node in ast.walk(stmt):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node)
                if not call_name:
                    continue
                if call_name in _LOAD_NAMES or any(
                    call_name == n for n in _LOAD_NAMES
                ):
                    has_load = True
                if call_name in _SAVE_NAMES:
                    if not in_lock:
                        has_save_unlocked = True
    return has_load, has_save_unlocked


def _call_name(node: ast.Call) -> str | None:
    """Extract the called function name (or attribute)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _scan_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file: str,
) -> LockSpanViolation | None:
    """Scan one function for the lost-update race pattern."""
    has_load, has_save_unlocked = _walk_with_lock_check(
        func.body, in_lock=False,
    )
    if has_load and has_save_unlocked:
        load_call = "(detected)"
        save_call = "(detected, outside any with-lock block)"
        return LockSpanViolation(
            file=file,
            function=func.name,
            lineno=func.lineno,
            load_call=load_call,
            save_call=save_call,
            description=(
                "Function " + func.name + " calls _load_X "
                "AND _save_X without holding a Lock/RLock "
                "spanning both calls. Lost-update race "
                "possible under concurrent invocation."
            ),
        )
    return None


def _scan_file(path: Path) -> tuple[list[LockSpanViolation], int]:
    """Scan one file. Returns (violations, function_count)."""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return [], 0
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return [], 0

    violations: list[LockSpanViolation] = []
    func_count = 0
    # Walk top-level + class-method functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_count += 1
            v = _scan_function(
                node,
                str(path).replace(os.sep, "/"),
            )
            if v is not None:
                violations.append(v)
    return violations, func_count


# Modules that have been audited + are KNOWN to handle locking
# elsewhere (e.g. via per-path lock acquired in a helper). These
# get exempted to keep the audit signal-to-noise high. Add to
# this list with a comment explaining WHY when exempting.
_EXEMPTIONS = {
    # action_log uses per-path lock via _lock_for(path) helper;
    # the AST audit can't see across function boundaries.
    "core/automation/action_log.py",
    # autonomy_overview_history uses _lock_for(path) helper.
    "core/automation/autonomy_overview_history.py",
    # thrash_block_log uses _lock_for(path) helper.
    "core/automation/thrash_block_log.py",
    # alert_history splits save into locked/unlocked variants.
    "core/approval/alert_history.py",
    # The audit itself contains string literals like _LOAD/_SAVE.
    "engines/_pattern_lockspan_audit.py",
}


def audit_pattern_lockspan(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> LockSpanReport:
    """Walk roots + flag load+save-without-spanning-lock patterns.

    Returns a report listing every candidate. Default scope:
    core/ + engines/ (excluding tests + __pycache__).
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (repo_root / "core", repo_root / "engines")

    violations: list[LockSpanViolation] = []
    scanned_files = 0
    scanned_functions = 0
    for root in roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            rel_str = str(py_path.relative_to(repo_root)).replace(
                os.sep, "/",
            )
            if rel_str in _EXEMPTIONS:
                continue
            scanned_files += 1
            file_violations, fc = _scan_file(py_path)
            scanned_functions += fc
            violations.extend(file_violations)

    return LockSpanReport(
        violations=tuple(violations),
        scanned_files=scanned_files,
        scanned_functions=scanned_functions,
    )
