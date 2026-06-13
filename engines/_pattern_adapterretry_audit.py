"""Pattern Adapter-Retry audit -- detect missing retry on 429/5xx in adapter HTTP helpers.

CLAUDE.md documents W962-64: secondary adapter bases (ads,
email, shipping, llm) raised IMMEDIATELY on 429 and 5xx
responses instead of retrying with backoff. The router's
fallback chain doesn't help because every adapter in the
class uses the same vendor endpoint.

Reference contract from data_pipeline/ingestion/api/shopify_
graphql.py + each of the post-W962-64 base files:

  def _http_request(...):
      for attempt in range(1, max_retries + 1):
          try:
              response = requests.X(...)
          except ConnectionError / Timeout:
              if attempt < max_retries:
                  time.sleep(backoff)
                  continue
              raise AdapterUnavailable / AdapterTimeout
          if response.status_code == 429:
              if attempt < max_retries:
                  time.sleep(retry_after or backoff)
                  continue
              raise AdapterRateLimited
          if 500 <= response.status_code < 600:
              if attempt < max_retries:
                  time.sleep(backoff)
                  continue
              raise AdapterUnavailable
          ...

This audit walks every file under core/adapters/*/_base.py
and verifies that any HTTP helper method:
  1. Has a `for attempt in range(...)` loop OR `while` retry
  2. Checks 429 status code
  3. Checks 5xx range (500 <= ... < 600)
  4. Uses time.sleep between attempts

Files exempted from this gate:
  - core/adapters/shopify/_base.py: defers to shopify_graphql
    client which already has retry.
  - core/adapters/_base.py (top-level abstract): no HTTP.

The audit is ADVISORY (does NOT fail CI). Surfaces gaps so
new adapter bases land with retry from day 1.
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdapterRetryViolation:
    file: str
    function: str
    lineno: int
    description: str


@dataclass(frozen=True)
class AdapterRetryReport:
    violations: tuple[AdapterRetryViolation, ...]
    scanned_files: int
    scanned_http_methods: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


# Files exempted from the audit (already correct via
# different mechanism).
_EXEMPTIONS = {
    "core/adapters/_base.py",      # abstract base, no HTTP
    "core/adapters/shopify/_base.py",  # defers to ShopifyGraphQL retry
    "core/adapters/registry.py",
    "core/adapters/router.py",
    "core/adapters/metrics.py",
    "core/adapters/errors.py",
    "core/adapters/sla.py",
    "core/adapters/__init__.py",
}


def _function_is_http_helper(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """True iff the function body calls requests.get / .post
    or urllib.request.urlopen."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr in ("get", "post", "put", "patch", "delete"):
                # heuristic: receiver value name contains 'request'
                # or '_requests'
                val = f.value
                if isinstance(val, ast.Name):
                    if "request" in val.id.lower():
                        return True
            if f.attr == "urlopen":
                return True
    return False


def _function_delegates_to_http_retry(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """W962-65: true iff the function delegates to
    core.adapters._http_retry.http_retry(...). The 11 adapter
    bases migrated to the shared helper replaced their inline
    retry loop with a delegation; treat that as audit-clean."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "http_retry":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "http_retry":
            return True
    return False


def _function_has_retry(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """True iff the function has a retry loop OR delegates to
    the shared http_retry helper:
      - for attempt in range(...) OR
      - while loop with `attempt` / `retries` counter
    AND time.sleep(...) inside that loop AND 429+5xx checks.
    OR core.adapters._http_retry.http_retry(...) call."""
    if _function_delegates_to_http_retry(func):
        return True
    has_loop = False
    has_sleep = False
    has_429 = False
    has_5xx = False
    for node in ast.walk(func):
        if isinstance(node, ast.For):
            # for X in range(...): with X named like attempt/retry
            if isinstance(node.target, ast.Name):
                tn = node.target.id.lower()
                if "attempt" in tn or "retry" in tn or "tries" in tn:
                    has_loop = True
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                if f.attr == "sleep":
                    has_sleep = True
        if isinstance(node, ast.Constant):
            if node.value == 429:
                has_429 = True
            if node.value == 500 or node.value == 600:
                has_5xx = True
        if isinstance(node, ast.Compare):
            # 500 <= X < 600 form
            for c in node.comparators:
                if isinstance(c, ast.Constant):
                    if c.value == 500 or c.value == 600:
                        has_5xx = True
            if isinstance(node.left, ast.Constant):
                if node.left.value == 500:
                    has_5xx = True
    return has_loop and has_sleep and has_429 and has_5xx


def _scan_file(
    path: Path, rel: str,
) -> tuple[list[AdapterRetryViolation], int]:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return [], 0

    # W962-65: only audit top-level class methods. The shared
    # http_retry helper takes a `_do_call` nested function which
    # would otherwise be flagged as its own HTTP helper.
    top_level_methods: list[
        ast.FunctionDef | ast.AsyncFunctionDef
    ] = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for m in cls.body:
            if isinstance(
                m, (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                top_level_methods.append(m)

    violations: list[AdapterRetryViolation] = []
    http_count = 0
    for node in top_level_methods:
        if not _function_is_http_helper(node):
            continue
        http_count += 1
        if _function_has_retry(node):
            continue
        violations.append(AdapterRetryViolation(
            file=rel,
            function=node.name,
            lineno=node.lineno,
            description=(
                node.name + " is an HTTP helper missing the "
                "retry pattern (need: for-loop on attempt/retry "
                "counter + time.sleep + 429 + 5xx checks)."
            ),
        ))
    return violations, http_count


def audit_pattern_adapterretry(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> AdapterRetryReport:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (repo_root / "core" / "adapters",)

    violations: list[AdapterRetryViolation] = []
    scanned_files = 0
    scanned_methods = 0
    for root in roots:
        if not root.exists():
            continue
        for py_path in root.rglob("_base.py"):
            if "__pycache__" in py_path.parts:
                continue
            rel = str(py_path.relative_to(repo_root)).replace(
                os.sep, "/",
            )
            if rel in _EXEMPTIONS:
                continue
            scanned_files += 1
            v, hc = _scan_file(py_path, rel)
            scanned_methods += hc
            violations.extend(v)

    return AdapterRetryReport(
        violations=tuple(violations),
        scanned_files=scanned_files,
        scanned_http_methods=scanned_methods,
    )
