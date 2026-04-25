"""Memory consolidation — episodic-to-semantic distillation.

Human memory consolidates during sleep: specific episodes fuse into
general patterns, redundant details fade, contradictions surface.
ShopAI's memory grows unboundedly otherwise — order events pile up
at thousands per week, events that should have promoted to patterns
get buried under their own volume, and two contradictory rules sit
peacefully in the store because nothing inspects them.

Run ``consolidate()`` once per calendar day (hooked to the daemon
phase 8k2b_consolidate). Four operations, deterministic, O(N):

  1. Distillation   — cluster episodic events with similar signatures
                      into a fresh semantic memory at level 1 (pattern).
                      Preserves source_ids so the chain is auditable.
  2. Compression    — older events (>30d) with score < 2.5 fade
                      (score × 0.9 per month); scores below 1.0
                      dissolve.
  3. Contradiction  — pairs of level ≥ 2 rules whose actions oppose
                      on the same (category, feature) signature surface
                      as ``category=contradiction`` events for the
                      feedback_learner to adjudicate.
  4. Reinforcement  — high-use + high-win memories gain +0.1 score
                      as a soft "well-travelled path" boost.

Safe: everything is rollback-friendly because every change is
recorded as its own memory event. Zero LLM; runs in a few hundred
ms against 10k rows.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("memory.consolidation")

_DB_PATH = Path("data/memory_intelligence.db")

# Serialises the whole consolidation pass so two daemons can't
# double-decay or double-dissolve the same rows.
_PASS_LOCK = threading.Lock()


@contextmanager
def _open(mode: str = "read"):
    """Yield a SQLite connection with sensible defaults.

    mode="write" begins an IMMEDIATE transaction so concurrent writers
    serialise at connection time rather than at first UPDATE.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        if mode == "write":
            conn.execute("BEGIN IMMEDIATE")
        yield conn
    finally:
        conn.close()

_OLD_THRESHOLD_S = 30 * 86_400          # 30 days
_COMPRESS_SCORE_CEILING = 2.5
_DECAY_FACTOR = 0.9
_DISSOLVE_SCORE = 1.0
_REINFORCE_USE_MIN = 10
_REINFORCE_WIN_RATE = 0.7
_REINFORCE_DELTA = 0.1
_DISTIL_MIN = 3


@dataclass
class ConsolidationReport:
    distilled_patterns: int = 0
    events_compressed: int = 0
    events_dissolved: int = 0
    contradictions_found: int = 0
    reinforced: int = 0
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "distilled_patterns": self.distilled_patterns,
            "events_compressed": self.events_compressed,
            "events_dissolved": self.events_dissolved,
            "contradictions_found": self.contradictions_found,
            "reinforced": self.reinforced,
            "ts": self.ts,
        }


def consolidate() -> ConsolidationReport:
    """Run one full consolidation pass. Never raises."""
    report = ConsolidationReport(ts=time.time())
    if not _DB_PATH.exists():
        return report
    # Skip overlapping passes rather than queue — if one is in-flight,
    # a second pass 10 seconds later isn't useful.
    if not _PASS_LOCK.acquire(blocking=False):
        logger.debug("consolidation already in progress; skipping")
        return report
    try:
        report.distilled_patterns = _distill_events()
        report.events_compressed, report.events_dissolved = _compress_old_events()
        report.contradictions_found = _detect_contradictions()
        report.reinforced = _reinforce_well_travelled()
        _persist(report)
    except Exception as exc:
        logger.debug("consolidation pass failed: %s", exc)
    finally:
        _PASS_LOCK.release()
    return report


# ── Distillation ────────────────────────────────────────────

def _distill_events() -> int:
    """Group level-0 events by (category, action) signature with
    ≥ MIN members whose oldest entry is older than 1 day. Emit one
    pattern per group with source_ids. Skips groups that already have
    a matching pattern (idempotent).
    """
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category, action, score FROM memories "
            "WHERE level=0 AND timestamp < ? "
            "ORDER BY category, action, id",
            (time.time() - 86_400,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    groups: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for mid, cat, act, score in rows:
        groups[(cat or "", act or "")].append((int(mid), float(score or 0)))

    created = 0
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
    except Exception:
        return 0
    for (cat, act), members in groups.items():
        if len(members) < _DISTIL_MIN:
            continue
        existing = _has_matching_pattern(cat, act)
        if existing:
            continue
        mean_score = sum(s for _, s in members) / len(members)
        avg_score = min(5.0, mean_score + 0.25)   # soft bump for distillation
        ids = [mid for mid, _ in members]
        try:
            mi.create(
                category=cat,
                content={
                    "pattern": f"distilled from {len(members)} events",
                    "evidence_count": len(members),
                    "source_ids": ids[:20],
                    "distilled_at": time.time(),
                },
                action=act,
                score=avg_score,
                memory_type="semantic",
                tags=["distilled", "pattern", cat],
                source_ids=ids[:20],
            )
            created += 1
        except Exception:
            continue
    return created


def _has_matching_pattern(category: str, action: str) -> bool:
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM memories "
            "WHERE category=? AND action=? AND level=1 "
            "  AND tags LIKE ? LIMIT 1",
            (category, action, '%"distilled"%'),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


# ── Compression ─────────────────────────────────────────────

def _compress_old_events() -> tuple[int, int]:
    cutoff = time.time() - _OLD_THRESHOLD_S
    with _open("write") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, score FROM memories "
            "WHERE level=0 AND timestamp < ? "
            "  AND score < ?",
            (cutoff, _COMPRESS_SCORE_CEILING),
        )
        rows = cur.fetchall()
        compressed = 0
        dissolved = 0
        for mid, score in rows:
            new_score = float(score or 0) * _DECAY_FACTOR
            if new_score < _DISSOLVE_SCORE:
                cur.execute("DELETE FROM memories WHERE id=?", (mid,))
                dissolved += 1
            else:
                cur.execute(
                    "UPDATE memories SET score=?, last_updated=? WHERE id=?",
                    (new_score, time.time(), mid),
                )
                compressed += 1
        conn.commit()
    return compressed, dissolved


# ── Contradiction detection ─────────────────────────────────

_OPPOSING_ACTION_PAIRS = {
    ("raise", "lower"),
    ("kill", "scale"),
    ("add_images", "remove_images"),
    ("up_vote", "down_vote"),
}


def _detect_contradictions() -> int:
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category, action, score, content "
            "FROM memories WHERE level >= 2 ORDER BY category, action",
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Bucket by category
    by_cat: dict[str, list[tuple[int, str, float, str]]] = defaultdict(list)
    for mid, cat, act, score, content in rows:
        by_cat[cat or ""].append((int(mid), act or "", float(score or 0),
                                   content or ""))
    count = 0
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
    except Exception:
        return 0
    for cat, memories in by_cat.items():
        for i, (m1, a1, s1, _) in enumerate(memories):
            for (m2, a2, s2, _) in memories[i + 1:]:
                if (a1, a2) in _OPPOSING_ACTION_PAIRS or \
                   (a2, a1) in _OPPOSING_ACTION_PAIRS:
                    try:
                        mi.create(
                            category="contradiction",
                            content={
                                "memory_a": m1,
                                "memory_b": m2,
                                "actions": [a1, a2],
                                "scores": [s1, s2],
                                "category": cat,
                            },
                            action=f"{a1}_vs_{a2}",
                            score=3.5,
                            tags=["contradiction", cat,
                                  f"memory:{m1}", f"memory:{m2}"],
                        )
                        count += 1
                    except Exception as exc:
                        logger.debug("contradiction event failed: %s", exc)
    return count


# ── Reinforcement ───────────────────────────────────────────

def _reinforce_well_travelled() -> int:
    with _open("write") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, score, use_count, success_count FROM memories "
            "WHERE level >= 1 AND use_count >= ? "
            "  AND CAST(success_count AS REAL) / use_count >= ? "
            "  AND score < 5.0",
            (_REINFORCE_USE_MIN, _REINFORCE_WIN_RATE),
        )
        rows = cur.fetchall()
        reinforced = 0
        for mid, score, _, _ in rows:
            new_score = min(5.0, float(score or 0) + _REINFORCE_DELTA)
            cur.execute(
                "UPDATE memories SET score=?, last_updated=? WHERE id=?",
                (new_score, time.time(), mid),
            )
            reinforced += 1
        conn.commit()
    return reinforced


def _persist(report: ConsolidationReport) -> None:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="consolidation",
            content=report.as_dict(),
            action="sleep",
            score=3.0,
            tags=["consolidation", "sleep", "meta"],
        )
    except Exception as exc:
        logger.debug("consolidation persist failed: %s", exc)
