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


def _collect_silent_sites(
    py_path: Path,
    base: Path,
) -> list[SilentSite]:
    """Walk one file's AST, return the list of silent-pass
    except-handlers."""
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

    rel = py_path.relative_to(base).as_posix()
    sites: list[SilentSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _is_just_pass(node):
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
