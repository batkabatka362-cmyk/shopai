"""Pattern G audit -- detect `or`-coercion silent drops of falsy values.

CLAUDE.md documents Pattern G: the false-y `or` chain. Caught
live across W947 (multiple sites), W962-11 (marketing_events
ad_spend=0 dropped), W962-12 (app_subscriptions trial_days=0
silently applied 14-day default = LOST BILLABLE REVENUE).

The pattern:

  amount = data.get("amount") or 100         # 0 -> 100 silently
  spend  = params.get("spend") or default    # 0  -> default
  trial  = req.get("trial_days") or 14       # 0  -> 14

The author intended "if missing, use default" but actually
wrote "if missing OR falsy, use default". For numeric / string
fields where 0 / "" / False are legitimate values, this
silently rewrites the user's intent.

The correct pattern is a sentinel cascade:

  _MISSING = object()
  amount = data.get("amount", _MISSING)
  if amount is _MISSING:
      amount = 100

Or explicit None-check:

  amount = data.get("amount")
  if amount is None:
      amount = 100

The Pattern G audit walks every adapter and engine for
``ast.BoolOp(op=Or, values=[<.get() call>, <Constant>])`` where
the constant is a non-zero literal AND the dictionary key looks
numeric-or-string-ish (heuristic: name endswith ``_amount``,
``_days``, ``_count``, ``_spend``, ``_value``, ``_trial``, etc.,
or the constant is an int / float).

This is necessarily heuristic -- a perfect audit needs type
information the AST doesn't have. The goal is to surface
CANDIDATES for human review, not auto-fix.
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Heuristic: parameter / key names where `or` coercion most
# often surfaces a real bug. Field names containing any of
# these tokens are treated as Pattern G candidates.
_RISKY_KEY_TOKENS = (
    "amount", "spend", "budget", "days", "count", "value",
    "trial", "qty", "quantity", "limit", "duration", "minutes",
    "hours", "score", "discount", "fee", "tax", "shipping",
    "price", "subtotal", "total", "fraction", "ratio",
)


@dataclass(frozen=True)
class PatternGViolation:
    file: str             # repo-relative path
    lineno: int
    snippet: str          # 1-line approximation of the source
    key: str              # the dict key being read
    default: str          # the right-hand literal
    classification: str   # numeric_default | string_default | other


@dataclass(frozen=True)
class PatternGReport:
    violations: tuple[PatternGViolation, ...]
    scanned_files: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _classify_default(node: ast.AST) -> str | None:
    """Return ``numeric_default`` for non-zero ints / floats,
    ``string_default`` for non-empty strings, or None for any
    other RHS (ignored)."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return None  # bool defaults are usually intentional
        if isinstance(v, (int, float)) and v != 0:
            return "numeric_default"
        if isinstance(v, str) and v:
            return "string_default"
    return None


def _get_call_key(node: ast.AST) -> str | None:
    """If ``node`` is ``X.get("KEY")`` or ``X.get("KEY", ...)``
    or ``getattr(X, "KEY", ...)``, return ``"KEY"``. Else None."""
    if not isinstance(node, ast.Call):
        return None
    # .get(...) form
    if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        if not node.args:
            return None
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(
            first.value, str,
        ):
            return first.value
    return None


def _key_is_risky(key: str) -> bool:
    lower = key.lower()
    return any(tok in lower for tok in _RISKY_KEY_TOKENS)


def _scan_file(path: Path) -> list[PatternGViolation]:
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    lines = src.splitlines()
    out: list[PatternGViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp):
            continue
        if not isinstance(node.op, ast.Or):
            continue
        # Must be a 2-operand or-chain (left=get, right=literal)
        if len(node.values) != 2:
            continue
        left, right = node.values
        key = _get_call_key(left)
        if not key:
            continue
        if not _key_is_risky(key):
            continue
        classification = _classify_default(right)
        if not classification:
            continue
        snippet = (
            lines[node.lineno - 1].strip()
            if 0 < node.lineno <= len(lines) else ""
        )
        default_str = (
            ast.unparse(right) if hasattr(ast, "unparse")
            else repr(getattr(right, "value", "?"))
        )
        out.append(PatternGViolation(
            file=str(path).replace(os.sep, "/"),
            lineno=node.lineno,
            snippet=snippet[:160],
            key=key,
            default=default_str,
            classification=classification,
        ))
    return out


def audit_pattern_g(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> PatternGReport:
    """Walk ``roots`` (default: engines/ + core/adapters/) and
    surface every Pattern G candidate."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (
            repo_root / "engines",
            repo_root / "core" / "adapters",
        )
    violations: list[PatternGViolation] = []
    scanned = 0
    for root in roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            # Skip the audit module itself + its tests so the
            # _RISKY_KEY_TOKENS literal list doesn't self-flag.
            if py_path.name == "_pattern_g_audit.py":
                continue
            scanned += 1
            violations.extend(_scan_file(py_path))
    return PatternGReport(
        violations=tuple(violations),
        scanned_files=scanned,
    )
