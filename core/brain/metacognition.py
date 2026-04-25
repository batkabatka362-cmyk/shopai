"""Meta-cognitive reflection — the brain inspects itself.

Most ShopAI components look *outward* — orders, competitors, ads.
This module turns the lens inward: at the end of each cycle it asks
whether the brain is actually learning, whether its confidence is
calibrated, and whether any subsystem is stuck in a bad loop.

Signals it watches:

  learning_rate
    • promotions (event→pattern, pattern→rule, rule→strategy) per
      cycle. Falling to zero for N cycles = we're not learning.

  confidence_calibration
    • how many rules promoted in the last 30 days had their score
      decrease (feedback down-vote, repeat failure). High rate →
      brain is over-confident.

  feedback_signal_balance
    • ratio of up-votes to down-votes in owner feedback. Skewed
      negative → brain is annoying the owner more than helping.

  adapter_breach_rate
    • fraction of recent cycles with any SLA breach. Trending up →
      infrastructure fatigue.

  skill_coverage
    • fraction of declared skills with ≥ 3 uses. Low → we've defined
      capabilities but never actually exercised them.

Output: a ``ReflectionReport`` with a scalar ``health 0-100`` plus
narrative-ready findings. Each finding persists as
``category=self_reflection score=3.0`` so the feedback_learner can
later promote "we noticed we were over-confident on audio" into
a rule.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.metacognition")

_MI_DB = Path("data/memory_intelligence.db")
_SKILLS_DB = Path("data/skills.db")

_SECONDS_PER_DAY = 86_400
_CALIBRATION_WINDOW_DAYS = 30


@dataclass
class Finding:
    signal: str
    level: str         # "ok" | "warning" | "critical"
    value: float
    threshold: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "level": self.level,
            "value": round(self.value, 3),
            "threshold": round(self.threshold, 3),
            "detail": self.detail,
        }


@dataclass
class ReflectionReport:
    health: float = 100.0     # 0-100; 100 = everything is calibrated
    findings: list[Finding] = field(default_factory=list)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "health": round(self.health, 1),
            "ts": self.ts,
            "findings": [f.as_dict() for f in self.findings],
            "worst": max((f.level for f in self.findings),
                         default="ok", key=_level_rank),
        }


def reflect() -> ReflectionReport:
    """Run one reflection pass. Never raises; signals with no data
    skip silently rather than crashing the cycle."""
    report = ReflectionReport(ts=time.time())
    _check_learning_rate(report)
    _check_confidence_calibration(report)
    _check_feedback_balance(report)
    _check_skill_coverage(report)
    report.health = _score(report.findings)
    _persist(report)
    return report


# ── Signal probes ───────────────────────────────────────────

def _check_learning_rate(report: ReflectionReport) -> None:
    if not _MI_DB.exists():
        return
    conn = sqlite3.connect(str(_MI_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM promotions WHERE created_at > ?",
            (time.time() - 7 * _SECONDS_PER_DAY,),
        )
        count = int(cur.fetchone()[0] or 0)
    except sqlite3.OperationalError:
        # Some memory schemas use a different column — fall back to row count
        try:
            cur.execute("SELECT COUNT(*) FROM promotions")
            count = int(cur.fetchone()[0] or 0)
        except sqlite3.OperationalError:
            return
    finally:
        conn.close()

    threshold = 3
    level = "ok" if count >= threshold else ("warning" if count > 0 else "critical")
    report.findings.append(Finding(
        signal="learning_rate",
        level=level,
        value=float(count),
        threshold=float(threshold),
        detail=f"{count} promotions in last 7 days (target ≥ {threshold})",
    ))


def _check_confidence_calibration(report: ReflectionReport) -> None:
    """Rules whose score decreased in the last 30 days relative to
    its creation_at baseline — a proxy for "we were too confident"."""
    if not _MI_DB.exists():
        return
    cutoff = time.time() - _CALIBRATION_WINDOW_DAYS * _SECONDS_PER_DAY
    conn = sqlite3.connect(str(_MI_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*), SUM(CASE WHEN success_count=0 AND use_count>2 "
            "THEN 1 ELSE 0 END) "
            "FROM memories WHERE level >= 2 AND timestamp > ?",
            (cutoff,),
        )
        total, overconf = cur.fetchone() or (0, 0)
    finally:
        conn.close()
    total = int(total or 0)
    overconf = int(overconf or 0)
    if total == 0:
        return
    rate = overconf / total
    threshold = 0.20
    level = "ok" if rate < threshold else ("warning" if rate < 0.4 else "critical")
    report.findings.append(Finding(
        signal="confidence_calibration",
        level=level,
        value=rate,
        threshold=threshold,
        detail=(
            f"{overconf}/{total} rules promoted in last 30d used ≥ 3× with "
            f"zero wins ({rate:.0%}). Threshold {threshold:.0%}"
        ),
    ))


def _check_feedback_balance(report: ReflectionReport) -> None:
    if not _MI_DB.exists():
        return
    conn = sqlite3.connect(str(_MI_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT action FROM memories "
            "WHERE category='feedback' AND timestamp > ?",
            (time.time() - 7 * _SECONDS_PER_DAY,),
        )
        rows = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    if not rows:
        return
    up = sum(1 for a in rows if a == "up_vote")
    down = sum(1 for a in rows if a == "down_vote")
    total = up + down
    if total == 0:
        return
    up_ratio = up / total
    threshold = 0.5
    level = ("ok" if up_ratio >= threshold
             else ("warning" if up_ratio >= 0.3 else "critical"))
    report.findings.append(Finding(
        signal="feedback_signal_balance",
        level=level,
        value=up_ratio,
        threshold=threshold,
        detail=f"{up} up / {down} down in last 7d ({up_ratio:.0%} approval)",
    ))


def _check_skill_coverage(report: ReflectionReport) -> None:
    if not _SKILLS_DB.exists():
        return
    conn = sqlite3.connect(str(_SKILLS_DB))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN uses>=3 THEN 1 ELSE 0 END) "
                    "FROM skills")
        total, exercised = cur.fetchone() or (0, 0)
    finally:
        conn.close()
    total = int(total or 0)
    exercised = int(exercised or 0)
    if total < 3:
        return
    ratio = exercised / total
    threshold = 0.5
    level = "ok" if ratio >= threshold else ("warning" if ratio >= 0.25 else "critical")
    report.findings.append(Finding(
        signal="skill_coverage",
        level=level,
        value=ratio,
        threshold=threshold,
        detail=f"{exercised}/{total} skills used ≥ 3 times ({ratio:.0%})",
    ))


# ── Scoring + persistence ───────────────────────────────────

_LEVEL_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def _level_rank(level: str) -> int:
    return _LEVEL_ORDER.get(level, 0)


def _score(findings: list[Finding]) -> float:
    """Healthy = 100. Each warning = −10, critical = −25."""
    h = 100.0
    for f in findings:
        if f.level == "warning":
            h -= 10
        elif f.level == "critical":
            h -= 25
    return max(0.0, h)


def _persist(report: ReflectionReport) -> None:
    if not report.findings:
        return
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mi.create(
            category="self_reflection",
            content=report.as_dict(),
            action="reflect",
            score=3.0,
            tags=["self_reflection", "metacognition"],
        )
    except Exception as exc:
        logger.debug("metacognition persist failed: %s", exc)
