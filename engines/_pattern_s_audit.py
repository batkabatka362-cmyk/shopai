"""Pattern S audit -- guards against silent ``except: pass``
blocks in production code.

The bug class this catches: a try/except where the except
body is LITERALLY just ``pass``, no logging, no re-raise, no
recovery action. The exception is silently swallowed --
operators get zero diagnostic signal when the path fails.

PRs #475-#478 in this codebase each fixed a real production
incident this pattern caused (telegram bot looking ""running""
while every poll failed; profit tracker silently losing writes;
SmartExecutor learning subsystem silently dead;
ShopifyAdapter health surface always reporting the same
generic ""unreachable"" message regardless of root cause). The
audit makes the same class of issue findable systematically
rather than one-grep-at-a-time.

Scope:
  - Only flags ``except: pass`` whose body is **exactly one
    ``pass`` statement**. Any other body (a log call, a
    re-raise, a return, an assignment) is considered an
    acceptable handling pattern. This is intentionally
    narrow -- false positives erode trust in the audit.
  - Skips ``tests/`` and ``scripts/`` (these legitimately
    use ``pass`` in test stubs / one-shot scripts).
  - Skips ``__pycache__``.

Public surface:
  - ``audit_pattern_s(roots=...)`` -> ``PatternSReport``
  - ``PatternSReport.has_violations``
  - CLI: ``shopai pattern-s-audit`` (wired in cli.py)
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.logger import get_logger

logger = get_logger("engines._pattern_s_audit")


# Directories whose Python files are NOT considered production
# code for the purposes of this audit. Tests intentionally use
# ``except: pass`` as stub-handler scaffolding; scripts are
# one-shot and don't warrant the same rigour.
_SKIP_DIRECTORIES = frozenset({"tests", "__pycache__", "scripts"})


# Files whose ``except: pass`` blocks are LEGITIMATE:
# ``utils/logger.py`` -- can't log a log-handler failure.
# Adding a path here is a deliberate operator decision; new
# silent-fail sites should add a logger.debug(...) call
# instead of being whitelisted.
_WHITELIST = frozenset({
    "utils/logger.py",
})


@dataclass(frozen=True)
class SilentSite:
    """One ``except: pass`` block with no diagnostic surface."""

    file: str           # relative path (POSIX)
    lineno: int          # line of the except clause


@dataclass(frozen=True)
class PatternSReport:
    silent_sites: list[SilentSite] = field(default_factory=list)
    scanned_modules: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.silent_sites)


def _is_just_pass(handler: ast.ExceptHandler) -> bool:
    """Body must be EXACTLY one ``pass`` statement -- no other
    statement (no log call, no re-raise, no assignment).
    Returns True when the handler is a silent swallow."""
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    return isinstance(stmt, ast.Pass)


_LOGGER_LEVELS = frozenset({
    "debug", "info", "warning", "error", "critical",
})


def _has_logger_call(node: ast.AST) -> bool:
    """True iff any descendant call's receiver attribute is a
    standard logger level. Used to detect the canonical
    ``rollback after a logged failure`` pattern."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and func.attr in _LOGGER_LEVELS:
            return True
    return False


def _find_owning_try(
    handler: ast.ExceptHandler,
    tree: ast.AST,
) -> ast.Try | None:
    """Return the ``Try`` statement that owns this handler."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and handler in node.handlers:
            return node
    return None


def _parent_block_and_index(
    target: ast.Try,
    tree: ast.AST,
) -> tuple[list[ast.stmt], int] | None:
    """Find the list-of-statements that contains ``target`` and
    the index where it lives.

    Python doesn't expose parent pointers on the AST, so we walk
    every node and look for one whose ``.body`` /
    ``.orelse`` / ``.finalbody`` / ``.handlers[].body`` list
    contains ``target``. Returns (block, index) or None when not
    found (shouldn't happen for a well-formed tree).
    """
    candidate_attrs = ("body", "orelse", "finalbody")
    for node in ast.walk(tree):
        for attr in candidate_attrs:
            block = getattr(node, attr, None)
            if not isinstance(block, list):
                continue
            try:
                idx = block.index(target)
            except ValueError:
                continue
            return block, idx
        # Also check ExceptHandler bodies (these are inside Try
        # nodes but not addressable via ``body``).
        if isinstance(node, ast.Try):
            for h in node.handlers:
                try:
                    idx = h.body.index(target)
                except ValueError:
                    continue
                return h.body, idx
    return None


def _statement_is_logger_call(stmt: ast.stmt) -> bool:
    """True iff the statement is a bare expression whose value
    is a call to a logger.<level>(...) method."""
    if not isinstance(stmt, ast.Expr):
        return False
    if not isinstance(stmt.value, ast.Call):
        return False
    func = stmt.value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _LOGGER_LEVELS
    )


def _inside_fall_through_chain(
    handler: ast.ExceptHandler,
    tree: ast.AST,
) -> bool:
    """True iff this handler is part of a ``parse fall-through``
    pattern: ``except: pass`` immediately followed in the same
    parent block by either:

      - Another ``try:`` statement (chained parse attempts).
      - A bare logger call (parse-then-log-on-fail).
      - A ``return`` statement (parse-then-return-default).

    Two canonical patterns this catches::

        # Fall-through to next strategy
        try:
            return float(s)
        except ValueError:
            pass
        try:
            return parse_iso(s)
        except ValueError:
            return fallback

        # Fall-through to single log at end
        for fmt in FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # ... try one more thing ...
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
        logger.warning("could not parse '%s'", s)
        return s
    """
    owning_try = _find_owning_try(handler, tree)
    if owning_try is None:
        return False
    return _statement_falls_through_to_marker(owning_try, tree)


def _is_fall_through_marker(stmt: ast.stmt) -> bool:
    """True iff the statement is a recognised end-of-chain
    marker: another try (chained parse), a bare logger call
    (parse-then-log), or a return (parse-then-return-default)."""
    if isinstance(stmt, ast.Try):
        return True
    if _statement_is_logger_call(stmt):
        return True
    if isinstance(stmt, ast.Return):
        return True
    return False


def _statement_falls_through_to_marker(
    target: ast.stmt,
    tree: ast.AST,
) -> bool:
    """True iff falling out of ``target`` naturally reaches a
    fall-through marker (another try, a logger call, or a
    return) within the same control-flow scope.

    Handles three nesting levels:

    1. ``target`` is followed by the marker in the same block::

           try: ...
           except: pass
           logger.warning(...)  # marker

    2. ``target`` is the LAST statement in an ``if`` body, and
       the ``if`` itself is followed by the marker. Falling out
       of the if-body is equivalent to falling out of the
       target in this case (since the only statement after
       the try IS the if-end)::

           if x:
               try: ...
               except: pass    # ``target``
           logger.warning(...)  # marker, after the if

    3. Same as (2) but the enclosing scope is an ``if`` body
       which is itself the last statement of an outer ``if``.
       Walk up the chain of if-bodies until we either find a
       sibling marker or fail.

    ``for``/``while`` bodies do NOT count for the walk-up --
    falling out of a loop body means ""next iteration"", not
    fall-through to the next sibling.
    """
    parent = _parent_block_and_index(target, tree)
    if parent is None:
        return False
    block, idx = parent
    # 1. Direct next sibling in the same block.
    if idx + 1 < len(block):
        nxt = block[idx + 1]
        if _is_fall_through_marker(nxt):
            return True
    # 2. If target is the last stmt in its parent block AND
    # the block IS the body of an ``if`` (not else, not a
    # loop), walk up to the if's siblings.
    if idx + 1 == len(block):
        # Find the if statement that owns ``block``.
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node.body is block:
                # Recursive walk: treat the if itself as the
                # new ``target`` and look for its successor.
                return _statement_falls_through_to_marker(
                    node, tree,
                )
    return False


def _inside_logged_except(
    handler: ast.ExceptHandler,
    tree: ast.AST,
) -> bool:
    """True iff this handler is nested inside another
    ExceptHandler whose body contains a logger call.

    The pattern is::

        except sqlite3.Error as exc:
            logger.warning("X failed: %s", exc)  # outer logs
            try:
                conn.rollback()
            except sqlite3.Error:
                pass                              # inner is OK

    The outer log already carries the diagnostic signal; the
    inner ``except: pass`` on the rollback is not a violation.

    Detection: walk every ExceptHandler in the tree; for each
    one OTHER than ``handler``, check whether ``handler``
    appears anywhere in its body. If so, check whether the
    OUTER handler has a logger call.
    """
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.ExceptHandler):
            continue
        if outer is handler:
            continue
        # Does outer's body contain `handler` as a descendant?
        for body_stmt in outer.body:
            for sub in ast.walk(body_stmt):
                if sub is handler:
                    # Found the nesting. Outer is logged -> skip.
                    for outer_stmt in outer.body:
                        if _has_logger_call(outer_stmt):
                            return True
                    # Outer is itself silent -- not a skip
                    # (the inner is still a violation; the
                    # outer one is too and is reported
                    # separately).
                    return False
    return False


# Substring markers in nearby comments that indicate the
# silent ``except: pass`` is INTENTIONAL. Operators
# explicitly opted in -- the audit respects that as long as
# the marker is present on the handler line, the pass line,
# or the line immediately before/after.
_INTENTIONAL_COMMENT_MARKERS = (
    "silently",         # ""# skip silently""
    "best-effort",      # ""# best-effort""
    "best effort",
    "intentional",      # ""# intentional fall-through""
    "fall through",     # ""# fall through to default""
    "fall-through",
    "no-op",            # ""# no-op when not present""
    "not present",      # ``list.remove`` idiom
    "tolerate",         # ""# tolerate corrupt rows""
    "degrade silently",
    "non-fatal",
)


def _has_intentional_marker_comment(
    handler: ast.ExceptHandler,
    src_lines: list[str],
) -> bool:
    """True iff the source code near this handler has an inline
    comment matching one of the recognised ``intentional``
    markers.

    Checked lines: the ``except`` line, the ``pass`` line, and
    the lines immediately before and after the handler.
    Matching is case-insensitive.
    """
    if not src_lines:
        return False
    # ast lines are 1-indexed; src_lines is 0-indexed.
    candidate_lines = set()
    for ln in (handler.lineno, handler.lineno + 1):
        # except line + pass line (the body is on the next line
        # for the canonical ``except X:\n    pass`` shape).
        candidate_lines.add(ln)
    # Also the line above the except and the line below the
    # pass, since operators sometimes put the comment there.
    candidate_lines.add(handler.lineno - 1)
    candidate_lines.add(handler.lineno + 2)

    for ln in candidate_lines:
        if 1 <= ln <= len(src_lines):
            line = src_lines[ln - 1].lower()
            # Quick gate: must contain a comment marker
            if "#" not in line:
                continue
            comment_part = line.split("#", 1)[1]
            for marker in _INTENTIONAL_COMMENT_MARKERS:
                if marker in comment_part:
                    return True
    return False


def _collect_silent_sites(
    py_path: Path,
    base: Path,
) -> list[SilentSite]:
    """Walk one file's AST, return the list of silent-pass
    except-handlers. Skips handlers nested inside a logged
    outer except (the standard ``rollback after a logged
    failure`` pattern is not a violation -- the outer log
    already carries the diagnostic signal)."""
    try:
        src = py_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("could not read %s: %s", py_path, exc)
        return []
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as exc:
        logger.debug("syntax error in %s: %s", py_path, exc)
        return []

    src_lines = src.splitlines()
    rel = py_path.relative_to(base).as_posix()
    sites: list[SilentSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_just_pass(node):
            continue
        if _inside_logged_except(node, tree):
            continue
        if _inside_fall_through_chain(node, tree):
            continue
        if _has_intentional_marker_comment(node, src_lines):
            continue
        sites.append(SilentSite(
            file=rel, lineno=node.lineno,
        ))
    return sites


def audit_pattern_s(
    *,
    roots: Iterable[Path | str] | None = None,
) -> PatternSReport:
    """Scan the configured roots for ``except: pass`` blocks
    whose body is exactly one ``pass`` statement.

    Args:
        roots: Iterable of directory paths to scan. Defaults to
            the repo root next to this module.

    Returns:
        ``PatternSReport`` with the list of silent sites.
    """
    if roots is None:
        here = Path(__file__).resolve().parent
        roots = [here.parent]  # repo root
    paths = [Path(r) for r in roots]

    sites: list[SilentSite] = []
    scanned = 0
    for root in paths:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            # Skip if any part of the path is in the skip list
            if any(p in _SKIP_DIRECTORIES for p in py_path.parts):
                continue
            scanned += 1
            rel = py_path.relative_to(root).as_posix()
            if rel in _WHITELIST:
                continue
            sites.extend(_collect_silent_sites(py_path, root))
    return PatternSReport(
        silent_sites=sites,
        scanned_modules=scanned,
    )
