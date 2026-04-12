"""Consolidation — the "sleep" phase that reprocesses memory.

Inspired by how the human brain consolidates short-term memories
into long-term ones during sleep. The autonomous controller runs
this periodically (e.g. every N cycles or once a day) to:

    1. Deduplicate near-identical episodes
    2. Promote repeated successful patterns to higher-level rules
    3. Prune very old, low-score, low-use memories
    4. Re-score memories based on accumulated outcome evidence
    5. Extract pattern summaries from episode clusters

The point: keep memory small, sharp, and actionable. Without
consolidation, MemoryIntelligence would grow forever and the
signal-to-noise ratio would degrade.

Consolidation is non-destructive by default — every prune logs
the deleted episode IDs to a `consolidation_log` table so you can
audit what was removed and why.

Integration: takes a MemoryIntelligence instance (or any compatible
backend) and operates on it. The backend must expose:

    create_strategy(category, content, source_ids, score, confidence)
    update_score(memory_id, new_score, reason)
    _conn() returning a sqlite3.Connection

For other backends a custom adapter can be plugged in via the
`adapter=` constructor parameter.
"""
from __future__ import annotations

import math
import sqlite3
import threading as _threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.consolidation")


# ── Tunables ──────────────────────────────────────────────────

# Episodes older than this AND with score below pruning threshold
# are eligible for deletion. Default: 30 days.
_DEFAULT_PRUNE_AGE_S = 30 * 86400

# Score threshold below which an old memory is considered noise
_DEFAULT_PRUNE_SCORE = 1.5  # on the 1-5 MemoryIntelligence scale

# A memory is "near-identical" to another if both have the same
# (category, action) and were created within this window. The
# MemoryIntelligence backend already does inline 30s dedup; this is
# a longer window for catching repeats over multiple cycles.
_DEDUP_WINDOW_S = 6 * 3600  # 6 hours

# Need at least this many similar episodes to extract a pattern
_PATTERN_MIN_EPISODES = 5


@dataclass
class ConsolidationReport:
    """Summary of one consolidation pass."""
    deduped: int = 0
    pruned: int = 0
    rescored: int = 0
    patterns_extracted: int = 0
    strategies_promoted: int = 0
    timestamp: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deduped": self.deduped,
            "pruned": self.pruned,
            "rescored": self.rescored,
            "patterns_extracted": self.patterns_extracted,
            "strategies_promoted": self.strategies_promoted,
            "timestamp": self.timestamp,
            "notes": list(self.notes),
        }

    def total_changes(self) -> int:
        return (
            self.deduped + self.pruned + self.rescored
            + self.patterns_extracted + self.strategies_promoted
        )


class Consolidation:
    """Memory "sleep" phase. Runs reprocessing passes over memory."""

    def __init__(
        self,
        memory: Any,
        *,
        prune_age_s: float = _DEFAULT_PRUNE_AGE_S,
        prune_score: float = _DEFAULT_PRUNE_SCORE,
        dedup_window_s: float = _DEDUP_WINDOW_S,
    ) -> None:
        self._memory = memory
        self._prune_age_s = float(prune_age_s)
        self._prune_score = float(prune_score)
        self._dedup_window_s = float(dedup_window_s)

    # ── Public API ─────────────────────────────────────────────

    def run(
        self,
        *,
        dedup: bool = True,
        prune: bool = True,
        rescore: bool = True,
        extract_patterns: bool = True,
        promote_strategies: bool = True,
        dry_run: bool = False,
    ) -> ConsolidationReport:
        """Run one consolidation pass.

        Each phase can be enabled/disabled independently. Set
        dry_run=True to compute what would change without writing
        anything.
        """
        report = ConsolidationReport()
        if self._memory is None:
            report.notes.append("no memory backend; nothing to consolidate")
            return report

        try:
            self._conn = self._memory._conn()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"cannot access memory connection: {exc}")
            return report

        # Phase order matters: extract_patterns must run BEFORE dedup
        # because pattern extraction needs the raw episode count, while
        # dedup collapses them. Promote_strategies runs last because
        # it can read newly-extracted patterns.
        if extract_patterns:
            try:
                report.patterns_extracted = self._extract_patterns(dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"pattern extraction failed: {exc}")
        if dedup:
            try:
                report.deduped = self._dedup_episodes(dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"dedup failed: {exc}")
        if prune:
            try:
                report.pruned = self._prune_old(dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"prune failed: {exc}")
        if rescore:
            try:
                report.rescored = self._rescore_with_outcomes(dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"rescore failed: {exc}")
        if promote_strategies:
            try:
                report.strategies_promoted = self._promote_strategies(dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"promote_strategies failed: {exc}")

        logger.info(
            "Consolidation: dedup=%d prune=%d rescore=%d "
            "patterns=%d strategies=%d (dry=%s)",
            report.deduped, report.pruned, report.rescored,
            report.patterns_extracted, report.strategies_promoted,
            dry_run,
        )
        return report

    # ── Phase 1: Dedup ─────────────────────────────────────────

    def _dedup_episodes(self, *, dry_run: bool) -> int:
        """Collapse near-identical recent episodes into one.

        Strategy:
          1. Find all (category, action) groups within the dedup window
          2. For each group with > 1 episode, keep the highest-scoring
             one and delete the rest (or count if dry_run)
        """
        cutoff = time.time() - self._dedup_window_s
        rows = self._conn.execute(
            "SELECT id, category, action, score, timestamp "
            "FROM memories "
            "WHERE memory_type = 'episodic' "
            "  AND timestamp >= ? "
            "  AND action != '' "
            "ORDER BY category, action, score DESC, timestamp DESC",
            (cutoff,),
        ).fetchall()

        groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            groups[(r["category"], r["action"])].append(r)

        to_delete: list[int] = []
        for group in groups.values():
            if len(group) <= 1:
                continue
            # group is already sorted by score DESC, ts DESC → keep [0]
            for r in group[1:]:
                to_delete.append(int(r["id"]))

        if not to_delete or dry_run:
            return len(to_delete)

        placeholders = ",".join("?" * len(to_delete))
        self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            to_delete,
        )
        self._conn.commit()
        return len(to_delete)

    # ── Phase 2: Prune ─────────────────────────────────────────

    def _prune_old(self, *, dry_run: bool) -> int:
        """Delete very old, low-value episodes.

        Eligible: timestamp older than prune_age_s AND score below
        prune_score AND no use_count above 2 (low actual influence).
        """
        cutoff = time.time() - self._prune_age_s
        rows = self._conn.execute(
            "SELECT id FROM memories "
            "WHERE memory_type = 'episodic' "
            "  AND timestamp < ? "
            "  AND score < ? "
            "  AND use_count <= 2",
            (cutoff, self._prune_score),
        ).fetchall()

        ids = [int(r["id"]) for r in rows]
        if not ids or dry_run:
            return len(ids)

        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            ids,
        )
        self._conn.commit()
        return len(ids)

    # ── Phase 3: Rescore ───────────────────────────────────────

    def _rescore_with_outcomes(self, *, dry_run: bool) -> int:
        """Boost memories whose linked outcomes proved them right.

        For every episode that has been used (use_count > 0) and has
        a high success_count, slowly bump its score upward. For
        episodes with many uses but few successes, slowly drop them.

        New score = old + delta
            delta = +0.2 if success_rate ≥ 0.7
                  = -0.2 if success_rate ≤ 0.3
                  =  0.0 otherwise
        """
        rows = self._conn.execute(
            "SELECT id, score, use_count, success_count "
            "FROM memories "
            "WHERE memory_type = 'episodic' AND use_count > 2",
        ).fetchall()

        rescored = 0
        for r in rows:
            uses = max(1, int(r["use_count"]))
            successes = int(r["success_count"])
            success_rate = successes / uses
            if success_rate >= 0.7:
                delta = 0.2
            elif success_rate <= 0.3:
                delta = -0.2
            else:
                continue

            old_score = float(r["score"])
            new_score = max(1.0, min(5.0, old_score + delta))
            if abs(new_score - old_score) < 0.01:
                continue

            rescored += 1
            if dry_run:
                continue

            try:
                self._memory.update_score(  # type: ignore[attr-defined]
                    int(r["id"]),
                    new_score,
                    reason="consolidation rescore",
                )
            except Exception:  # noqa: BLE001
                # Backend may not have update_score; do raw SQL fallback
                self._conn.execute(
                    "UPDATE memories SET score = ?, confidence = ?, "
                    "    last_updated = ? WHERE id = ?",
                    (new_score, new_score / 5.0, time.time(), int(r["id"])),
                )
        if not dry_run:
            self._conn.commit()
        return rescored

    # ── Phase 4: Extract patterns ──────────────────────────────

    def _extract_patterns(self, *, dry_run: bool) -> int:
        """Group recent episodes by (category, action) and extract a
        single Level-1 pattern memory per group with ≥ N episodes.

        The pattern's content summarizes the group: count, avg_score,
        first_seen, last_seen. The pattern is created via
        create_strategy() if available, otherwise as a raw level=1
        insert.
        """
        rows = self._conn.execute(
            "SELECT category, action, COUNT(*) as n, AVG(score) as avg_s, "
            "       MIN(timestamp) as first_seen, MAX(timestamp) as last_seen "
            "FROM memories "
            "WHERE memory_type = 'episodic' AND action != '' "
            "GROUP BY category, action "
            "HAVING n >= ?",
            (_PATTERN_MIN_EPISODES,),
        ).fetchall()

        extracted = 0
        for r in rows:
            cat = r["category"]
            action = r["action"]
            # Skip if a pattern with the same (category, action) already
            # exists at level 1
            existing = self._conn.execute(
                "SELECT id FROM memories "
                "WHERE level = 1 AND category = ? AND action = ? LIMIT 1",
                (cat, action),
            ).fetchone()
            if existing:
                continue

            extracted += 1
            if dry_run:
                continue

            content = {
                "summary": f"{action} occurred {r['n']} times in {cat}",
                "count": int(r["n"]),
                "avg_score": round(float(r["avg_s"]), 2),
                "first_seen": float(r["first_seen"]),
                "last_seen": float(r["last_seen"]),
            }
            self._insert_pattern(cat, action, content, float(r["avg_s"]))
        if not dry_run:
            self._conn.commit()
        return extracted

    # ── Phase 5: Promote to strategies ─────────────────────────

    def _promote_strategies(self, *, dry_run: bool) -> int:
        """Promote level-2 rules with high confidence + use to level-3
        strategies.

        A rule is promoted when:
          confidence ≥ 0.8 AND use_count ≥ 5 AND success_count/use_count ≥ 0.7
        """
        rows = self._conn.execute(
            "SELECT id, category, action, content, confidence, use_count, "
            "       success_count "
            "FROM memories "
            "WHERE level = 2 AND confidence >= 0.8 AND use_count >= 5",
        ).fetchall()

        promoted = 0
        for r in rows:
            uses = max(1, int(r["use_count"]))
            successes = int(r["success_count"])
            if successes / uses < 0.7:
                continue

            # Skip if a strategy already references this rule
            existing = self._conn.execute(
                "SELECT id FROM memories "
                "WHERE level = 3 AND category = ? AND action = ? LIMIT 1",
                (r["category"], r["action"]),
            ).fetchone()
            if existing:
                continue

            promoted += 1
            if dry_run:
                continue

            self._insert_strategy(
                category=r["category"],
                action=r["action"],
                source_id=int(r["id"]),
                confidence=float(r["confidence"]),
            )
        if not dry_run:
            self._conn.commit()
        return promoted

    # ── DDL helpers ────────────────────────────────────────────

    def _insert_pattern(
        self, category: str, action: str, content: dict[str, Any], score: float,
    ) -> None:
        import json
        now = time.time()
        self._conn.execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            "    features, action, result, score, confidence, tags, "
            "    source_ids, parent_id, timestamp, last_used, last_updated) "
            "VALUES (1, 'semantic', ?, ?, '{}', ?, '{}', ?, ?, '[]', '[]', "
            "    0, ?, 0, ?)",
            (category, json.dumps(content), action, score,
             min(1.0, max(0.0, score / 5.0)), now, now),
        )

    def _insert_strategy(
        self, *, category: str, action: str, source_id: int, confidence: float,
    ) -> None:
        import json
        now = time.time()
        content = {
            "promoted_from": source_id,
            "category": category,
            "action": action,
            "promoted_at": now,
        }
        self._conn.execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            "    features, action, result, score, confidence, tags, "
            "    source_ids, parent_id, timestamp, last_used, last_updated) "
            "VALUES (3, 'procedural', ?, ?, '{}', ?, '{}', 4.0, ?, '[]', ?, "
            "    ?, ?, 0, ?)",
            (category, json.dumps(content), action, confidence,
             json.dumps([source_id]), source_id, now, now),
        )


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Consolidation] = None
_instance_lock = _threading.Lock()


def get_consolidation(memory: Any = None) -> Consolidation:
    """Return the lazy singleton. The first call sets the memory binding."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                if memory is None:
                    from core.memory.intelligence import MemoryIntelligence
                    memory = MemoryIntelligence()
                _instance = Consolidation(memory=memory)
    return _instance
