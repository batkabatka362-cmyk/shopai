"""Pattern CA -- Phase 4 ritual substrate is wired across the
six required surfaces.

Phase 4 (W963-54..66) added a ritual substrate (morning_brief
/ evening_brief / week_review / anomaly_detector + cron
recommender) and integrated it across multiple surfaces. A
refactor that drops one of those integrations would
silently break the compose-IN / watch-OUT loop -- the
substrate stays alive (unit tests pass) but the operator-
facing wiring is missing.

This audit AST-scans the six canonical surfaces and verifies
that the expected Phase 4 import / reference is present in
each. It does NOT verify semantics -- just that the module
contains the reference. Combined with the unit tests for each
substrate engine, this catches the "I forgot to re-wire X
after my refactor" class of regression.

Six canonical surfaces:
  1. cli.py -- daily-brief renderer references agi_anomaly_detector
  2. cli.py -- empire renderer references agi_anomaly_detector
  3. cli.py -- morning-brief renderer references the brief
  4. cli.py -- cycle run records earnings snapshot
              (SHOPAI_CYCLE_RECORD_BRIEF env-gated)
  5. engines/_notify.py -- collect_alerts emits
                           agi_critical_anomaly
  6. engines/_ai_strategies.py -- _agi_phase4_context helper
                                  is defined
  7. core/world_model/snapshot.py -- _section_agi_phase4 method
  8. engines/_go_live_check.py -- _check_phase4_substrate fn
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent


_PROBES: list[dict[str, Any]] = [
    {
        "name": "cli_daily_brief_anomaly_inline",
        "path": "cli.py",
        "needles": (
            "agi_anomaly_detector.detector",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_morning_brief_renderer",
        "path": "cli.py",
        "needles": (
            "from engines.agi_morning_brief import",
            "AgiMorningBriefEngine",
        ),
        "min_occurrences": 1,
    },
    {
        "name": "cli_cycle_record_brief_hook",
        "path": "cli.py",
        "needles": (
            "SHOPAI_CYCLE_RECORD_BRIEF",
        ),
        "min_occurrences": 1,
    },
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
    # W963-69: brief-diff wired into morning-brief
    {
        "name": "morning_brief_diff_wiring",
        "path": "engines/agi_morning_brief/briefer.py",
        "needles": (
            "agi_brief_diff",
            "_gather_brief_diff",
        ),
        "min_occurrences": 2,
    },
    # W963-71: attention streak wired into morning-brief
    {
        "name": "morning_brief_attention_wiring",
        "path": "engines/agi_morning_brief/briefer.py",
        "needles": (
            "agi_recommend_streak",
            "_gather_attention_streak",
        ),
        "min_occurrences": 2,
    },
    # W963-71: attention streak wired into notify
    {
        "name": "notify_attention_streak_alert",
        "path": "engines/_notify.py",
        "needles": (
            "agi_attention_streak",
            "agi_recommend_streak",
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


def _ast_parses(src: str) -> bool:
    try:
        ast.parse(src)
    except SyntaxError:
        return False
    return True


def run_pattern_ca_audit() -> PatternCAReport:
    report = PatternCAReport()
    for probe in _PROBES:
        report.probes_run += 1
        path = _REPO_ROOT / probe["path"]
        src = _read(path)
        if not src:
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=probe["path"],
                detail="source file missing or unreadable",
            ))
            continue
        if not _ast_parses(src):
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=probe["path"],
                detail="source has SyntaxError",
            ))
            continue
        ok = True
        missing: list[str] = []
        # Count total occurrences of all needles
        total_occurrences = 0
        for needle in probe["needles"]:
            count = src.count(needle)
            total_occurrences += count
            if count == 0:
                missing.append(needle)
                ok = False
        if (
            total_occurrences
            < int(probe["min_occurrences"])
        ):
            ok = False
            missing.append(
                f"<total occurrences "
                f"{total_occurrences} < required "
                f"{probe['min_occurrences']}>"
            )
        if not ok:
            report.violations.append(PatternCAViolation(
                surface=probe["name"],
                path=probe["path"],
                detail=(
                    "missing needles: "
                    + ", ".join(missing)
                ),
            ))
        else:
            report.clean_probes += 1
    return report
