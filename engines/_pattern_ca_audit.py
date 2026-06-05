"""Pattern CA -- Phase 4 ritual substrate is wired across the
canonical surfaces.

Phase 4 (W963-54..71) added a ritual substrate (morning_brief /
evening_brief / week_review / anomaly_detector + cron
recommender + brief-diff + recommend-streak) and integrated it
across multiple surfaces. A refactor that drops one of those
integrations would silently break the compose-IN / watch-OUT
loop -- the substrate stays alive (unit tests pass) but the
operator-facing wiring is missing.

W963-74: previously this audit just string-grepped each file
for needles. That missed function-LEVEL placement bugs
(see W963-72: anomaly probes string-present in cli.py but in
_cmd_empire instead of _cmd_daily_brief). Now probes can
optionally specify ``enclosing_function`` -- when set, the
needle MUST appear inside that function's AST body, not
merely anywhere in the module.

Probe types:
  - default: file must contain N+ occurrences of each needle
  - enclosing_function: needles must appear inside the
    specified top-level function definition
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent


_PROBES: list[dict[str, Any]] = [
    # ── cli.py: function-scope probes (W963-74 tightening)
    {
        "name": "cli_daily_brief_anomaly_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_daily_brief",
        "needles": (
            "agi_anomaly_detector",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_daily_brief_attention_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_daily_brief",
        "needles": (
            "agi_recommend_streak",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_daily_brief_earnings_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_daily_brief",
        "needles": (
            "agi_earnings_summary",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_empire_anomaly_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_empire",
        "needles": (
            "agi_anomaly_detector",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_empire_attention_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_empire",
        "needles": (
            "agi_recommend_streak",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_empire_earnings_inline",
        "path": "cli.py",
        "enclosing_function": "_cmd_empire",
        "needles": (
            "agi_earnings_summary",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_morning_brief_handler",
        "path": "cli.py",
        "enclosing_function": "_cmd_morning_brief",
        "needles": (
            "AgiMorningBriefEngine",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_cycle_record_brief_hook",
        "path": "cli.py",
        "enclosing_function": "_cmd_cycle_run",
        "needles": (
            "SHOPAI_CYCLE_RECORD_BRIEF",
        ),
        "min_occurrences": 1,
    },
    # W963-77: cycle-status Phase 4 verdict + trajectory
    {
        "name": "cli_cycle_status_phase4_block",
        "path": "cli.py",
        "enclosing_function": "_cmd_cycle_status",
        "needles": (
            "agi_earnings_summary",
            "agi_brief_diff",
            "agi_recommend_streak",
            "agi_anomaly_detector",
        ),
        "min_occurrences": 4,
    },
    # ── Non-cli probes: file-level scan
    {
        "name": "notify_agi_anomaly_alert",
        "path": "engines/_notify.py",
        "needles": (
            "agi_critical_anomaly",
            "agi_anomaly_detector",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "notify_attention_streak_alert",
        "path": "engines/_notify.py",
        "needles": (
            "agi_attention_streak",
            "agi_recommend_streak",
        ),
        "min_occurrences": 2,
    },
    # W963-75: brief-diff regression alert
    {
        "name": "notify_brief_diff_alert",
        "path": "engines/_notify.py",
        "needles": (
            "agi_brief_regression",
            "agi_brief_diff",
        ),
        "min_occurrences": 2,
    },
    {
        "name": "ai_strategies_phase4_helper",
        "path": "engines/_ai_strategies.py",
        "needles": (
            "_agi_phase4_context",
        ),
        "min_occurrences": 2,  # def + 1+ caller
    },
    {
        "name": "world_model_phase4_section",
        "path": "core/world_model/snapshot.py",
        "needles": (
            "_section_agi_phase4",
            "agi_phase4",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "go_live_phase4_check",
        "path": "engines/_go_live_check.py",
        "needles": (
            "_check_phase4_substrate",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "morning_brief_diff_wiring",
        "path": "engines/agi_morning_brief/briefer.py",
        "needles": (
            "agi_brief_diff",
            "_gather_brief_diff",
        ),
        "min_occurrences": 2,
    },
    {
        "name": "morning_brief_attention_wiring",
        "path": "engines/agi_morning_brief/briefer.py",
        "needles": (
            "agi_recommend_streak",
            "_gather_attention_streak",
        ),
        "min_occurrences": 2,
    },
]


@dataclass
class PatternCAViolation:
    surface: str
    path: str
    detail: str


@dataclass
class PatternCAReport:
    probes_run: int = 0
    clean_probes: int = 0
    violations: list[PatternCAViolation] = field(
        default_factory=list,
    )

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse(src: str) -> ast.Module | None:
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def _find_function(
    tree: ast.Module, name: str,
) -> ast.FunctionDef | None:
    """Find the first top-level function definition with the
    given name. Returns None if not found."""
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return node
    return None


def _function_source(
    src: str, fn_node: ast.FunctionDef,
) -> str:
    """Return the source slice of a function node."""
    lines = src.splitlines(keepends=True)
    start = fn_node.lineno - 1
    end = fn_node.end_lineno or fn_node.lineno
    return "".join(lines[start:end])


def _check_probe(
    probe: dict[str, Any],
    src: str,
    tree: ast.Module,
) -> tuple[bool, list[str]]:
    """Returns (ok, missing_list)."""
    scope = probe.get("enclosing_function")
    if scope:
        fn = _find_function(tree, scope)
        if fn is None:
            return (
                False,
                [
                    f"enclosing function {scope!r} not found",
                ],
            )
        haystack = _function_source(src, fn)
    else:
        haystack = src

    missing: list[str] = []
    total = 0
    for needle in probe["needles"]:
        count = haystack.count(needle)
        total += count
        if count == 0:
            missing.append(needle)
    min_occ = int(probe["min_occurrences"])
    if total < min_occ:
        missing.append(
            f"<total occurrences {total} < required "
            f"{min_occ}>"
        )
    return (not missing, missing)


def run_pattern_ca_audit() -> PatternCAReport:
    report = PatternCAReport()
    # Cache parsed sources to avoid reparsing for each probe
    cache: dict[str, tuple[str, ast.Module | None]] = {}
    for probe in _PROBES:
        report.probes_run += 1
        rel = probe["path"]
        if rel not in cache:
            cache[rel] = (
                _read(_REPO_ROOT / rel),
                None,
            )
        src, tree = cache[rel]
        if not src:
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=rel,
                detail="source file missing or unreadable",
            ))
            continue
        if tree is None:
            parsed = _parse(src)
            cache[rel] = (src, parsed)
            tree = parsed
        if tree is None:
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=rel,
                detail="source has SyntaxError",
            ))
            continue
        ok, missing = _check_probe(probe, src, tree)
        if not ok:
            scope_str = (
                f" inside {probe['enclosing_function']}()"
                if probe.get("enclosing_function") else ""
            )
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=rel,
                detail=(
                    f"missing needles{scope_str}: "
                    + ", ".join(missing)
                ),
            ))
        else:
            report.clean_probes += 1
    return report


def _ast_parses(src: str) -> bool:
    """Back-compat helper for tests written against the old
    string-grep version of the audit."""
    return _parse(src) is not None
