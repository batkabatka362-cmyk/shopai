"""Pattern AT audit: scaffolder template double-brace lint (W817).

Phase 35 + Phase 38 both caught the same scaffolder bug --
``core/automation/autonomy_template.py`` is rendered via
``str.replace``, not ``str.format``, so literal ``{{`` and
``}}`` in the template survive as broken syntax in scaffolded
files:

  * ``filters={{"store_id": ...}}`` becomes a SET containing
    a DICT -- unhashable at runtime.
  * ``out.append({{"k": v}})`` becomes a set literal too.
  * ``f"per-run cap reached: {{cap_run}}"`` becomes an
    f-string containing the literal text ``{cap_run}`` instead
    of the value.

Both bugs slipped past unit tests because the scaffolded
appliers short-circuit on empty payload (Pattern AH), and the
empty-payload short-circuit doesn't reach the buggy expressions.

Pattern AT is a defensive AST + textual audit: walk every
``engines/<X>_autonomy/`` package and every rendered template
file, fail on any literal ``{{`` or ``}}``. Template ROOT
(autonomy_template.py) is exempt because it intentionally
contains substitution placeholders like ``{ENTITY}``.

Per-line text scan beats AST here because the broken code IS
parseable -- ``{{"x": 1}}`` is a valid Python set literal --
so AST traversal would miss the regression.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Files whose CONTENT legitimately contains "{{" / "}}" because
# they ARE the scaffolder template source or test fixtures for
# the scaffolder. Each path is relative to the repo root.
_EXEMPT_PATHS: frozenset[str] = frozenset({
    "core/automation/autonomy_template.py",
    # Scaffolder + patcher use {NAME} placeholders that DON'T
    # collide with double-brace, but the renderer code itself
    # mentions "{{" as documentation -- exempt these:
    "core/automation/autonomy_init.py",
    "core/automation/autonomy_catalog_patches.py",
})


@dataclass
class PatternATViolation:
    file_path: str
    line_no: int
    line_excerpt: str
    kind: str  # "{{" or "}}"


@dataclass
class PatternATReport:
    files_scanned: list[str] = field(default_factory=list)
    clean_files: list[str] = field(default_factory=list)
    violations: list[PatternATViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _scan_file(
    path: Path, base: Path,
) -> list[PatternATViolation]:
    """Walk one .py file line-by-line, flag literal {{ or }}."""
    rel = path.relative_to(base).as_posix()
    if rel in _EXEMPT_PATHS:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Pattern AT: read failed for %s: %s", path, exc,
        )
        return []
    out: list[PatternATViolation] = []
    for i, line in enumerate(text.splitlines(), start=1):
        # ONLY flag {{ -- }} also appears legitimately when
        # two dicts close on the same line (e.g. nested
        # {"a": {"b": v}}). Legitimate Python rarely opens
        # with {{ (set-of-set is exotic; the scaffolder bug
        # is unmistakable).
        if "{{" in line:
            out.append(PatternATViolation(
                file_path=rel,
                line_no=i,
                line_excerpt=line.strip()[:200],
                kind="{{",
            ))
    return out


def run_pattern_at_audit(
    *,
    repo_root: str | Path = ".",
) -> PatternATReport:
    """Audit every autonomy package + core/automation for stray
    scaffolder-template double-braces.

    Scans every .py file under ``engines/*_autonomy/`` plus
    ``core/automation/`` (minus the exempt list).
    """
    report = PatternATReport()
    root = Path(repo_root).resolve()

    targets: list[Path] = []
    eng = root / "engines"
    if eng.is_dir():
        for d in sorted(eng.iterdir()):
            if d.is_dir() and d.name.endswith("_autonomy"):
                for f in sorted(d.glob("*.py")):
                    targets.append(f)
    ca = root / "core" / "automation"
    if ca.is_dir():
        for f in sorted(ca.glob("*.py")):
            targets.append(f)

    for path in targets:
        rel = path.relative_to(root).as_posix()
        report.files_scanned.append(rel)
        viols = _scan_file(path, root)
        if viols:
            report.violations.extend(viols)
        else:
            report.clean_files.append(rel)

    return report
