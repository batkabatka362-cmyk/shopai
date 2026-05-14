"""Dispatcher coverage audit — find action_types enqueued by engines
but missing a registered dispatcher.

Pattern K (CLAUDE.md): the queue accepts an arbitrary string
``action_type`` at enqueue time, but execution requires a matching
dispatcher in ``core.approval.dispatchers``. A missing dispatcher
fails silently at execute time, *not* enqueue time. PR #102 found
12 engine writebacks that had enqueue helpers but no dispatchers —
every approved action from those engines was a no-op.

This module preempts the recurrence. It AST-scans ``engines/`` for
``.enqueue(action_type=...)`` literal keyword arguments and
cross-references against ``list_registered_action_types()``. Any
mismatch is a Pattern K candidate the next CI run should fail on.

Limitations:
- Only literal string keyword args are detected (matches the
  prevailing engine convention).
- Action types built dynamically (string interpolation, dict
  lookups) are skipped — but no engine uses that pattern today.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnqueueCall:
    """One ``.enqueue(action_type="X", ...)`` call site."""

    action_type: str
    file_path: str
    line: int


@dataclass(frozen=True)
class AuditReport:
    """Outcome of a single audit pass."""

    enqueued: list[EnqueueCall]
    registered: list[str]
    missing: list[str]
    orphaned: list[str]

    @property
    def has_gaps(self) -> bool:
        return bool(self.missing)


def find_enqueue_call_sites(root: Path) -> list[EnqueueCall]:
    """Walk ``root`` recursively, AST-parse every ``*.py``, and
    return the literal ``action_type`` kwargs passed to
    ``.enqueue(...)`` calls. Non-literal kwargs are skipped.
    """
    sites: list[EnqueueCall] = []
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Only ``X.enqueue(...)`` calls — attribute access on
            # anything (a queue, a get_approval_queue() return).
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "enqueue"
            ):
                continue
            for kw in node.keywords:
                if kw.arg != "action_type":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str,
                ):
                    sites.append(EnqueueCall(
                        action_type=kw.value.value,
                        file_path=str(path),
                        line=node.lineno,
                    ))
    return sites


def audit_coverage(engines_root: Path | str = "engines") -> AuditReport:
    """Cross-reference ``engines/`` enqueue calls against the
    registered dispatcher table.

    Returns an :class:`AuditReport` with two gap lists:
    - ``missing``: action_types engines enqueue but no dispatcher
      handles. These are Pattern K bugs — silent failures at
      execute time.
    - ``orphaned``: action_types with a dispatcher but no engine
      enqueuing them. These are dead code or future scaffolding.
    """
    from core.approval.executor import list_registered_action_types
    # Trigger registration via lazy import.
    import core.approval.dispatchers  # noqa: F401

    root = Path(engines_root)
    sites = find_enqueue_call_sites(root)
    used = {s.action_type for s in sites}
    registered = set(list_registered_action_types())
    missing = sorted(used - registered)
    orphaned = sorted(registered - used)
    return AuditReport(
        enqueued=sites,
        registered=sorted(registered),
        missing=missing,
        orphaned=orphaned,
    )
