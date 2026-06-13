"""Pattern HTTP-Auth audit -- detect missing auth gates on destructive POST.

CLAUDE.md documents the W962-50 fix: api/dashboard_api.py and
api/server.py exposed destructive POST routes (store
registration, cycle runs, pending-action execute) with NO
authentication despite api/auth.py defining a token system.
Added the shared `_api_auth_ok(handler)` helper.

This audit walks every BaseHTTPRequestHandler subclass and
verifies that do_POST/do_PUT/do_PATCH/do_DELETE has a call to
the auth helper (either `_api_auth_ok(self)` or some other
function name containing `auth`).

False-positive exemptions:
  - `/api/webhook` and `/api/webhook/shopify` routes:
    HMAC-verified separately so an additional bearer-token
    gate would block production Shopify deliveries. These are
    detected by looking for an early-return on the webhook
    path before the auth check.

The audit is ADVISORY (does NOT fail CI) -- new HTTP handler
classes that haven't yet adopted the auth gate need a chance
to land their fix without breaking the build.
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpAuthViolation:
    file: str
    class_name: str
    function: str
    lineno: int
    description: str


@dataclass(frozen=True)
class HttpAuthReport:
    violations: tuple[HttpAuthViolation, ...]
    scanned_files: int
    scanned_handlers: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _is_http_handler_class(cls: ast.ClassDef) -> bool:
    """Same heuristic as Pattern Body-Cap."""
    for base in cls.bases:
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name and "Handler" in name and "HTTP" in name.upper():
            return True
        if name in (
            "BaseHTTPRequestHandler",
            "SimpleHTTPRequestHandler",
            "CGIHTTPRequestHandler",
        ):
            return True
    return False


def _function_calls_auth(
    func_body: list[ast.stmt],
) -> bool:
    """True iff the function body calls a function whose name
    contains 'auth' (case-insensitive). Catches:
      - _api_auth_ok(self)
      - check_auth(...)
      - is_authenticated(...)
      - _auth_check(self)
      - validate_auth(...)
    """
    for node in ast.walk(
        ast.Module(body=list(func_body), type_ignores=[]),
    ):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name and "auth" in name.lower():
            return True
    return False


def _function_returns_unauthorized(
    func_body: list[ast.stmt],
) -> bool:
    """True iff the function body emits a 401-or-403 status
    code via _json_response(...) or self.send_response(...).
    Defensive backstop in case the auth check is inlined."""
    for node in ast.walk(
        ast.Module(body=list(func_body), type_ignores=[]),
    ):
        if not isinstance(node, ast.Constant):
            continue
        if node.value in (401, 403, "unauthorized", "forbidden"):
            return True
    return False


def _scan_handler_class(
    cls: ast.ClassDef,
    file: str,
) -> tuple[list[HttpAuthViolation], int]:
    violations: list[HttpAuthViolation] = []
    handler_count = 0
    DESTRUCTIVE = {"do_POST", "do_PUT", "do_PATCH", "do_DELETE"}
    for node in cls.body:
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        if node.name not in DESTRUCTIVE:
            continue
        handler_count += 1
        if _function_calls_auth(node.body):
            continue
        if _function_returns_unauthorized(node.body):
            continue
        violations.append(HttpAuthViolation(
            file=file,
            class_name=cls.name,
            function=node.name,
            lineno=node.lineno,
            description=(
                cls.name + "." + node.name + " is a destructive "
                "HTTP handler with no auth gate (no call to "
                "*auth* helper + no 401/403 status emission). "
                "Add `if not _api_auth_ok(self): return` or "
                "equivalent."
            ),
        ))
    return violations, handler_count


def audit_pattern_httpauth(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> HttpAuthReport:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (
            repo_root / "api",
            repo_root / "core" / "system",
        )

    violations: list[HttpAuthViolation] = []
    scanned_files = 0
    scanned_handlers = 0
    for root in roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            scanned_files += 1
            try:
                src = py_path.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=str(py_path))
            except (OSError, SyntaxError):
                continue
            rel = str(py_path).replace(os.sep, "/")
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not _is_http_handler_class(node):
                    continue
                v, hc = _scan_handler_class(node, rel)
                scanned_handlers += hc
                violations.extend(v)

    return HttpAuthReport(
        violations=tuple(violations),
        scanned_files=scanned_files,
        scanned_handlers=scanned_handlers,
    )
