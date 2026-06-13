"""Pattern CC -- persistence helpers stay consolidated.

W963-92 hoisted Pattern J guard + atomic JSON write +
tolerant JSON load into ``core.agi.persistence`` and
migrated 7 W963-44+ engine modules. Pattern CC prevents
those 7 from drifting back to local copies.

Rules enforced (AST):

  1. Migrated modules MUST NOT define their own
     ``_is_test_environment`` function. (Importing it from
     core.agi.persistence and aliasing as
     ``_is_test_environment`` IS allowed.)

  2. Migrated modules MUST NOT use ``tempfile.mkstemp``.
     They should call ``atomic_write_json`` instead.

A new audit gate (the 30th) -- catches drift before merge.

Scope: ONLY the modules migrated in W963-92. Legacy
modules (the other 17 with local _is_test_environment
definitions) are intentionally left out of scope; their
migration is W963-93+ work and Pattern CC will be widened
incrementally.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


# W963-92 migrated set. Adding a new file to this set
# means the migration is complete; the file becomes
# subject to Pattern CC.
_MIGRATED_FILES: frozenset[str] = frozenset({
    "engines/agi_earnings_history/store.py",
    "engines/agi_arm_recommender/auto_disarm_log.py",
    "engines/strategist_memory/store.py",
    "engines/daily_pnl_history/store.py",
    "engines/fleet_notifier/state.py",
    "engines/agi_morning_brief/briefer.py",
    "engines/earn_config/configurator.py",
})


@dataclass
class PatternCCViolation:
    rule: str          # "redefines_guard" | "uses_mkstemp"
    path: str
    line: int
    detail: str


@dataclass
class PatternCCReport:
    files_checked: int = 0
    violations: list[PatternCCViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _redefines_guard(tree: ast.Module) -> tuple[bool, int]:
    """True if the module has a `def _is_test_environment`
    function definition (NOT an alias import)."""
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_is_test_environment"
        ):
            return True, node.lineno
    return False, 0


def _uses_mkstemp(tree: ast.Module) -> tuple[bool, int]:
    """True if the module calls tempfile.mkstemp anywhere."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # tempfile.mkstemp(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "mkstemp"
        ):
            return True, node.lineno
        # bare mkstemp(...) after `from tempfile import mkstemp`
        if (
            isinstance(func, ast.Name)
            and func.id == "mkstemp"
        ):
            return True, node.lineno
    return False, 0


def run_pattern_cc_audit() -> PatternCCReport:
    report = PatternCCReport()
    for rel in sorted(_MIGRATED_FILES):
        path = _REPO_ROOT / rel
        if not path.exists():
            report.violations.append(PatternCCViolation(
                rule="missing_file",
                path=rel,
                line=0,
                detail=(
                    "expected migrated file does not "
                    "exist -- has it been removed?"
                ),
            ))
            continue
        report.files_checked += 1
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError) as exc:
            report.violations.append(PatternCCViolation(
                rule="parse_error",
                path=rel,
                line=0,
                detail=str(exc),
            ))
            continue
        redef, redef_line = _redefines_guard(tree)
        if redef:
            report.violations.append(PatternCCViolation(
                rule="redefines_guard",
                path=rel,
                line=redef_line,
                detail=(
                    "migrated module redefines "
                    "_is_test_environment locally -- "
                    "import from core.agi.persistence"
                ),
            ))
        mkstemp, mkstemp_line = _uses_mkstemp(tree)
        if mkstemp:
            report.violations.append(PatternCCViolation(
                rule="uses_mkstemp",
                path=rel,
                line=mkstemp_line,
                detail=(
                    "migrated module calls "
                    "tempfile.mkstemp -- call "
                    "atomic_write_json() from "
                    "core.agi.persistence instead"
                ),
            ))
    return report
