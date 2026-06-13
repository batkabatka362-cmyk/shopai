"""Pattern HTTP-BodyCap audit -- detect unbounded request-body reads.

CLAUDE.md documents the unbounded-body DoS class caught at W962-40:

  def do_POST(self):
      length = int(self.headers.get("Content-Length", 0))
      body = self.rfile.read(length)   # length is untrusted!

An attacker sending Content-Length: 999999999 would cause the
receiver to allocate ~10GB into memory. Shopify webhooks are
well under 100KB; cap at 1MB.

This audit walks every BaseHTTPRequestHandler subclass and
checks that any rfile.read(N) where N comes from a header is
preceded by a bound check.

Detection rules:
  1. Find a function in a class with BaseHTTPRequestHandler in
     its base classes (heuristic).
  2. Walk the function body for `self.rfile.read(EXPR)` calls.
  3. If EXPR is a variable that traces back to int(header_get),
     check whether a numeric comparison (`<`, `<=`, `>`, `>=`)
     against a literal precedes the read.
  4. If no bound check is found, flag the read.

The audit is ADVISORY (does NOT fail CI). Targets HTTP
servers (api/dashboard_api.py + api/server.py + others).
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BodyCapViolation:
    file: str
    class_name: str
    function: str
    lineno: int
    description: str


@dataclass(frozen=True)
class BodyCapReport:
    violations: tuple[BodyCapViolation, ...]
    scanned_files: int
    scanned_handlers: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _is_http_handler_class(cls: ast.ClassDef) -> bool:
    """True iff the class subclasses BaseHTTPRequestHandler
    (or a known subclass like DashboardAPIHandler etc.)."""
    for base in cls.bases:
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name and "Handler" in name and "HTTP" in name.upper():
            return True
        # Tighter check for direct subclasses
        if name in (
            "BaseHTTPRequestHandler",
            "SimpleHTTPRequestHandler",
            "CGIHTTPRequestHandler",
        ):
            return True
    return False


def _is_rfile_read(node: ast.Call) -> bool:
    """True iff this Call looks like `self.rfile.read(...)`."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "read":
        return False
    val = func.value
    if not isinstance(val, ast.Attribute):
        return False
    if val.attr != "rfile":
        return False
    if not isinstance(val.value, ast.Name):
        return False
    return val.value.id == "self"


def _function_has_bound_check(func_body: list[ast.stmt]) -> bool:
    """True iff the function body contains a numeric comparison
    against a literal that looks like a body-size bound check
    (`if length > N`, `if size <= MAX`, etc.). Heuristic: any
    Compare node comparing a Name to an int/float literal."""
    for node in ast.walk(ast.Module(body=list(func_body), type_ignores=[])):
        if not isinstance(node, ast.Compare):
            continue
        # Left side is a Name (the variable being bounded)
        if not isinstance(node.left, ast.Name):
            # Could also be int(headers.get(...)) on the left
            if not (
                isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "int"
            ):
                continue
        # Right side has a numeric literal
        for cmp_node in node.comparators:
            if isinstance(cmp_node, ast.Constant) and isinstance(
                cmp_node.value, (int, float),
            ):
                # Filter: must be a non-trivial size (>1000 bytes)
                if cmp_node.value >= 1000:
                    return True
            # Also accept comparison against a Name like MAX_BODY_BYTES
            if isinstance(cmp_node, ast.Name) and (
                "MAX" in cmp_node.id.upper()
                or "LIMIT" in cmp_node.id.upper()
                or "CAP" in cmp_node.id.upper()
                or "BOUND" in cmp_node.id.upper()
            ):
                return True
    return False


def _scan_handler_class(
    cls: ast.ClassDef,
    file: str,
) -> tuple[list[BodyCapViolation], int]:
    """Scan one handler class for unbounded reads."""
    violations: list[BodyCapViolation] = []
    handler_count = 0
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Focus on do_POST / do_PUT / do_PATCH where bodies arrive
        if not node.name.startswith("do_"):
            continue
        handler_count += 1
        has_bound = _function_has_bound_check(node.body)
        # Walk for rfile.read() calls
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            if not _is_rfile_read(sub):
                continue
            # If no args, this is read() until EOF — also unbounded
            # (urllib BaseHTTPRequestHandler reads until socket
            # closes), but typically not exploitable in practice.
            # Flag anyway.
            if not has_bound:
                violations.append(BodyCapViolation(
                    file=file,
                    class_name=cls.name,
                    function=node.name,
                    lineno=sub.lineno,
                    description=(
                        cls.name + "." + node.name + " calls "
                        "self.rfile.read() without a bound check "
                        "on the read size (no `if length > N` "
                        "found before the read)."
                    ),
                ))
    return violations, handler_count


def _scan_file(
    path: Path,
) -> tuple[list[BodyCapViolation], int]:
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return [], 0
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return [], 0

    violations: list[BodyCapViolation] = []
    handler_count = 0
    rel_str = str(path).replace(os.sep, "/")
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_http_handler_class(node):
            continue
        v, hc = _scan_handler_class(node, rel_str)
        violations.extend(v)
        handler_count += hc
    return violations, handler_count


def audit_pattern_bodycap(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> BodyCapReport:
    """Walk roots + flag unbounded rfile.read calls."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (repo_root / "api", repo_root / "core" / "system")

    violations: list[BodyCapViolation] = []
    scanned_files = 0
    scanned_handlers = 0
    for root in roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            scanned_files += 1
            v, hc = _scan_file(py_path)
            scanned_handlers += hc
            violations.extend(v)

    return BodyCapReport(
        violations=tuple(violations),
        scanned_files=scanned_files,
        scanned_handlers=scanned_handlers,
    )
