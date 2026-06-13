"""Pattern Atomic-Write audit -- detect non-atomic JSON writes.

CLAUDE.md documents the corrupt-file-on-crash class caught
across W962-15/27/28/31/35/36/37/38/41/42/43/45/46. The
non-atomic pattern:

  with path.open("w") as f:
      json.dump(state, f)   # crash mid-write -> half file
  # OR
  path.write_text(json.dumps(state))   # same problem

A crash (segfault, OOM, power loss, ctrl-C) between open and
close leaves a half-truncated JSON file that subsequent
readers reject as malformed, silently returning an empty
state (effectively losing every persisted record).

The correct pattern:

  tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
  tmp.write_text(json.dumps(state))
  os.replace(tmp, path)   # ATOMIC on POSIX + Windows

This audit walks every module that writes JSON to disk and
flags non-atomic writes.

Detection rules:
  1. Find function calls matching `path.write_text(...)`,
     `path.open("w", ...)`, or `f.write(json.dumps(...))`.
  2. Check whether the same function performs `os.replace(...)`
     or `tmp.replace(...)` (the rename-to-final pattern).
  3. If no rename pattern is found, flag the write.

False positives:
  - Single-line config writes where atomicity isn't critical
  - Test fixtures that legitimately overwrite without atomicity
  - Cache writes that are non-critical

The audit is ADVISORY (does NOT fail CI). Surfaces candidates.
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtomicWriteViolation:
    file: str
    function: str
    lineno: int
    description: str


@dataclass(frozen=True)
class AtomicWriteReport:
    violations: tuple[AtomicWriteViolation, ...]
    scanned_files: int
    scanned_functions: int

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _is_path_write_text(node: ast.Call) -> bool:
    """True iff this Call is `X.write_text(...)` where X looks
    like a path."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "write_text":
        return False
    return True


def _is_path_open_w(node: ast.Call) -> bool:
    """True iff this Call is `X.open("w", ...)` for writing."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "open":
        return False
    # First arg should be "w" / "wb" / "wt"
    if not node.args:
        return False
    arg0 = node.args[0]
    if not isinstance(arg0, ast.Constant):
        return False
    if not isinstance(arg0.value, str):
        return False
    return arg0.value.startswith("w")


def _writes_json_in_function(func_body: list[ast.stmt]) -> bool:
    """True iff this function writes JSON to disk (i.e. has a
    Call to json.dump or json.dumps near a path-write)."""
    has_path_write = False
    has_json_dump = False
    for node in ast.walk(ast.Module(body=list(func_body), type_ignores=[])):
        if isinstance(node, ast.Call):
            if _is_path_write_text(node) or _is_path_open_w(node):
                has_path_write = True
            # json.dump / json.dumps
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in (
                "dump", "dumps",
            ):
                # Check parent value is json
                if isinstance(func.value, ast.Name):
                    if func.value.id == "json":
                        has_json_dump = True
    return has_path_write and has_json_dump


def _function_has_atomic_rename(
    func_body: list[ast.stmt],
) -> bool:
    """True iff the function uses os.replace or Path.replace
    (the atomic-rename pattern)."""
    for node in ast.walk(ast.Module(body=list(func_body), type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "replace":
            continue
        # os.replace(src, dst) — value is Name "os"
        if isinstance(func.value, ast.Name) and func.value.id == "os":
            return True
        # tmp.replace(path) — value is Name (a Path object)
        # Heuristic: name contains tmp/temp
        if isinstance(func.value, ast.Name):
            n = func.value.id.lower()
            if "tmp" in n or "temp" in n:
                return True
    return False


def _scan_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file: str,
) -> AtomicWriteViolation | None:
    """Scan one function for the non-atomic JSON write pattern."""
    if not _writes_json_in_function(func.body):
        return None
    if _function_has_atomic_rename(func.body):
        return None
    return AtomicWriteViolation(
        file=file,
        function=func.name,
        lineno=func.lineno,
        description=(
            "Function " + func.name + " writes JSON via "
            "path.write_text(...) or open(w) + json.dump "
            "without using os.replace(tmp, dst). A crash "
            "mid-write would leave a corrupt JSON file."
        ),
    )


# Exemptions for files that are intentionally non-atomic
# (test fixtures, scaffolders, transient caches).
_EXEMPTIONS = {
    # The audit itself contains write_text examples in
    # docstrings + comments.
    "engines/_pattern_atomicwrite_audit.py",
    # Scaffolders write template-rendered files; atomicity
    # not critical (operator re-runs on failure).
    "core/automation/autonomy_init.py",
    "core/automation/autonomy_catalog_patcher.py",
    "core/automation/autonomy_template.py",
    # OAuth code save is single-write; the file is
    # transient (consumed once).
    "core/auth/oauth_code_capture.py",
}


def audit_pattern_atomicwrite(
    roots: tuple[Path, ...] | None = None,
    *,
    repo_root: Path | None = None,
) -> AtomicWriteReport:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if roots is None:
        roots = (
            repo_root / "core",
            repo_root / "engines",
        )

    violations: list[AtomicWriteViolation] = []
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
            try:
                src = py_path.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=str(py_path))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    scanned_functions += 1
                    v = _scan_function(node, rel_str)
                    if v is not None:
                        violations.append(v)

    return AtomicWriteReport(
        violations=tuple(violations),
        scanned_files=scanned_files,
        scanned_functions=scanned_functions,
    )
