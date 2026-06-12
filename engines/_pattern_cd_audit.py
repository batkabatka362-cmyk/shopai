"""W963-141: Pattern CD audit -- engine.run callsites
in production entry points must be wrapped in
active_store(...).

THE CONTRACT

The per-store substrate (W963-115..140) only works if
engine.run is called inside a `with active_store(sid):`
context manager. Pre-fix four entry points dropped
this wrap silently:

  - cycle controller       (W963-127)
  - webhook handler        (W963-128)
  - cycle snapshot loop    (W963-131)
  - approval executor      (W963-133)

All four caused money-class misattribution before
their wraps landed. A future commit that adds a 5th
entry point without the wrap would silently regress
the substrate to env-default routing.

Pattern CD codifies the wrap as an institutional gate:
every production engine.run callsite (in cli.py,
core/autonomous, core/webhooks, core/approval) MUST be
inside a `with active_store(...)` block OR be in the
exempt list.

EXEMPT MODULES

Some engine.run callers are caller-driven and inherit
the wrap from their caller's context. Including these
in the strict check would generate false positives:

  - engines/<name>/__init__.py (engine self-wrapping
    helpers used inside other engines)
  - core/chaining/*.py (engine chaining; wrap is the
    chain caller's responsibility)
  - core/performance/batch_processor.py (batch utility)
  - core/testing/*.py (test code)
  - core/system/*.py (low-level system orchestrator)
  - core/orchestrator/main_orchestrator.py (legacy)
  - core/bridge/__init__.py (bridge utility)
  - tests/*.py (test code)
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Production paths where the audit is STRICT
_STRICT_FILES = (
    "cli.py",
    "core/autonomous/",
    "core/webhooks/",
    "core/approval/",
)

# Exempt paths (caller-driven, test code, or legacy)
_EXEMPT_PATTERNS = (
    "tests/",
    "core/chaining/",
    "core/performance/",
    "core/testing/",
    "core/system/",
    "core/orchestrator/",
    "core/bridge/",
    "core/context/",
    "engines/_pattern_cd_audit.py",
)


@dataclass
class CallsiteFinding:
    file: str
    line: int
    function: str
    has_wrap: bool
    note: str = ""


# Functions inside STRICT files whose wrap lives in
# their CALLER's function -- the AST audit can't see
# across function boundaries so we exempt them by
# (file_suffix, function_name) tuples.
_CALLER_WRAPPED = (
    # core/autonomous/controller.py: run_cycle wraps the
    # whole cycle body in active_store(sid) before
    # calling _phase_analyze (W963-127 design).
    ("core/autonomous/controller.py", "_phase_analyze"),
    # core/webhooks/__init__.py: handle() wraps each
    # _trigger_engine call in active_store(webhook_sid)
    # (W963-128 design).
    ("core/webhooks/__init__.py", "_trigger_engine"),
)


@dataclass
class PatternCDReport:
    strict_callsites: list[CallsiteFinding] = field(
        default_factory=list,
    )
    exempt_callsites: list[CallsiteFinding] = field(
        default_factory=list,
    )
    unwrapped: list[CallsiteFinding] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return bool(self.unwrapped)


def _is_engine_run_call(node: ast.AST) -> bool:
    """True iff node is `engine.run(...)` or
    `engine_instance.run(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "run":
        return False
    if not isinstance(func.value, ast.Name):
        return False
    return func.value.id in (
        "engine", "engine_instance",
    )


def _is_active_store_call(expr: ast.AST) -> bool:
    """True iff expr is a call whose function name
    contains 'active_store' (covers active_store,
    _w963_127_active_store, etc.)."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name):
        return "active_store" in func.id
    if isinstance(func, ast.Attribute):
        return "active_store" in func.attr
    return False


def _has_active_store_wrap(
    body: list[ast.stmt], target_lineno: int,
) -> bool:
    """Recursively walk body for a With/AsyncWith block
    that ENCLOSES target_lineno + has an active_store
    call as its context expr."""
    for node in body:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            end = getattr(node, "end_lineno", None) or 0
            if node.lineno <= target_lineno <= end:
                for item in node.items:
                    if _is_active_store_call(
                        item.context_expr,
                    ):
                        return True
                if _has_active_store_wrap(
                    node.body, target_lineno,
                ):
                    return True
        # Recurse into common compound statements
        for attr in ("body", "orelse", "finalbody"):
            child = getattr(node, attr, None)
            if (
                isinstance(child, list)
                and _has_active_store_wrap(
                    child, target_lineno,
                )
            ):
                return True
        # ExceptHandler list inside Try
        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for h in handlers:
                inner = getattr(h, "body", None)
                if (
                    isinstance(inner, list)
                    and _has_active_store_wrap(
                        inner, target_lineno,
                    )
                ):
                    return True
    return False


def _scan_file(path: Path) -> list[CallsiteFinding]:
    findings: list[CallsiteFinding] = []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError) as exc:
        logger.debug(
            "pattern_cd scan %s raised: %s", path, exc,
        )
        return findings
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        for sub in ast.walk(node):
            if not _is_engine_run_call(sub):
                continue
            line = getattr(sub, "lineno", 0)
            wrapped = _has_active_store_wrap(
                node.body, line,
            )
            findings.append(CallsiteFinding(
                file=str(path),
                line=line,
                function=node.name,
                has_wrap=wrapped,
            ))
    return findings


def _is_strict_path(
    path: Path, root: Path,
) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(rel.startswith(p) for p in _STRICT_FILES)


def _is_exempt_path(
    path: Path, root: Path,
) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(
        rel.startswith(p) or rel == p
        for p in _EXEMPT_PATTERNS
    )


def audit_pattern_cd(
    *, repo_root: Path | None = None,
) -> PatternCDReport:
    """Run the audit. Strict callsites without an
    active_store wrap populate the .unwrapped list (=
    violation). Exempt callsites are listed for
    visibility only."""
    repo_root = (
        repo_root
        or Path(__file__).resolve().parent.parent
    )
    report = PatternCDReport()
    for path in repo_root.rglob("*.py"):
        rel = path.relative_to(repo_root).as_posix()
        if "__pycache__" in rel or ".git" in rel:
            continue
        is_strict = _is_strict_path(path, repo_root)
        is_exempt = _is_exempt_path(path, repo_root)
        if not is_strict and not is_exempt:
            continue
        if is_exempt and not is_strict:
            for f in _scan_file(path):
                report.exempt_callsites.append(f)
            continue
        for f in _scan_file(path):
            report.strict_callsites.append(f)
            if f.has_wrap:
                continue
            # Caller-wrapped exemption check
            rel = (
                Path(f.file)
                .relative_to(repo_root)
                .as_posix()
            )
            is_caller_wrapped = any(
                rel.endswith(suffix)
                and fn == f.function
                for suffix, fn in _CALLER_WRAPPED
            )
            if is_caller_wrapped:
                f.note = (
                    "wrap inherited from caller"
                )
                report.exempt_callsites.append(f)
            else:
                report.unwrapped.append(f)
    return report
