"""Causal inference — why did X happen?

When a launch dies, the evaluator gives the verdict ("kill, ROAS
0.8") but not the *cause*. This module looks at the memory timeline
around the moment of death and proposes a ranked set of candidate
causes (competitor undercut, creative swap, niche trend reversal,
adapter outage) with evidence per candidate.

Algorithm (determinism > intelligence):

  1. Anchor on the ``category=launch`` event for the target launch
     and the verdict timestamp from the evaluator.
  2. Pull every memory within a ±7-day window of the anchor.
  3. Bucket by category (competitor, trend, launch, self_critique,
     anomaly, adapter_sla, order).
  4. Score each candidate with ``evidence_strength = events_in_window
     × avg_score × recency_weight``. Higher = more likely root cause.
  5. Return a ``CausalReport`` listing the top-K candidates with
     supporting memory ids so the owner can audit.

The Oracle (v1-D7) + Chat session (v2-D1) can wrap this with natural
language; this module stays LLM-free so it's cheap enough to run on
every kill advisory.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")
_WINDOW_DAYS = 7
_SECONDS_PER_DAY = 86_400


_CANDIDATE_CATEGORIES = (
    "competitor",      # competitor price drop could undercut us
    "trend",           # inflection in broader metric
    "self_critique",   # we just retuned thresholds — maybe we're wrong
    "anomaly",         # external anomaly detector picked it up
    "adapter_sla",     # LLM / Shopify / Meta Ads degraded
    "order",           # cluster of failed orders
    "launch",          # a sibling launch grabbed attention/budget
)


@dataclass
class Candidate:
    category: str
    evidence_count: int
    avg_score: float
    recency_weight: float       # [0, 1]; 1 = right at anchor
    strength: float             # ranking score
    sample_memory_ids: list[int] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "evidence_count": self.evidence_count,
            "avg_score": round(self.avg_score, 2),
            "recency_weight": round(self.recency_weight, 3),
            "strength": round(self.strength, 3),
            "sample_memory_ids": self.sample_memory_ids[:5],
            "summary": self.summary,
        }


@dataclass
class CausalReport:
    target_kind: str                 # "launch" | "query"
    target_id: str
    anchor_ts: float
    candidates: list[Candidate] = field(default_factory=list)
    window_days: int = _WINDOW_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "anchor_ts": self.anchor_ts,
            "window_days": self.window_days,
            "candidates": [c.as_dict() for c in self.candidates],
        }


def investigate_launch(launch_id: str) -> CausalReport:
    """Trace potential causes for the verdict on *launch_id*."""
    anchor = _launch_anchor(launch_id)
    if anchor is None:
        return CausalReport(
            target_kind="launch", target_id=launch_id, anchor_ts=0.0,
        )
    report = CausalReport(
        target_kind="launch",
        target_id=launch_id,
        anchor_ts=anchor,
    )
    _populate(report)
    return report


def investigate_event(anchor_ts: float, label: str = "custom") -> CausalReport:
    """Trace causes around a specific timestamp — e.g. a cycle error
    or an anomaly emitted by the trend detector."""
    report = CausalReport(
        target_kind="query",
        target_id=label,
        anchor_ts=float(anchor_ts),
    )
    _populate(report)
    return report


# ── Internals ────────────────────────────────────────────────

def _launch_anchor(launch_id: str) -> float | None:
    """Return the timestamp of the launch's most recent verdict
    memory; falls back to the registration event timestamp."""
    if not launch_id or not _DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        # The persisted JSON uses ``"launch_id": "..."`` with a space
        # after the colon, so we match on the launch_id token alone
        # with a bounded context to avoid false positives.
        cur.execute(
            "SELECT timestamp FROM memories "
            "WHERE category='launch' AND content LIKE ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (f'%{launch_id}%',),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return float(row[0]) if row else None


def _populate(report: CausalReport) -> None:
    if not _DB_PATH.exists() or not report.anchor_ts:
        return
    lo = report.anchor_ts - report.window_days * _SECONDS_PER_DAY
    hi = report.anchor_ts + report.window_days * _SECONDS_PER_DAY

    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category, action, content, score, timestamp "
            "FROM memories "
            "WHERE timestamp BETWEEN ? AND ? "
            "  AND category IN ({}) "
            "ORDER BY timestamp DESC".format(
                ",".join("?" * len(_CANDIDATE_CATEGORIES))
            ),
            (lo, hi, *_CANDIDATE_CATEGORIES),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    by_cat: dict[str, list[tuple[int, float, float, str]]] = {}
    for mid, category, action, content_json, score, ts in rows:
        by_cat.setdefault(category, []).append(
            (int(mid), float(score or 0), float(ts), action or ""),
        )

    for category, entries in by_cat.items():
        if not entries:
            continue
        ids = [e[0] for e in entries[:5]]
        avg_score = sum(e[1] for e in entries) / len(entries)
        # Recency weight: closer to anchor → stronger. Exponential decay
        # with 2-day half-life.
        recency = sum(
            math.exp(-abs(e[2] - report.anchor_ts) / (2 * _SECONDS_PER_DAY))
            for e in entries
        ) / len(entries)
        strength = len(entries) * avg_score * recency
        summary = _summary_for(category, entries)
        report.candidates.append(Candidate(
            category=category,
            evidence_count=len(entries),
            avg_score=avg_score,
            recency_weight=recency,
            strength=strength,
            sample_memory_ids=ids,
            summary=summary,
        ))

    report.candidates.sort(key=lambda c: -c.strength)


def _summary_for(category: str, entries: list[tuple[int, float, float, str]]) -> str:
    actions = [e[3] for e in entries if e[3]]
    if not actions:
        return f"{len(entries)} {category} events nearby"
    top_action = max(set(actions), key=actions.count)
    return (
        f"{len(entries)} {category} events; most common action "
        f"'{top_action}' × {actions.count(top_action)}"
    )
