"""Tests for the cognitive Consolidation phase.

These exercise consolidation against a real MemoryIntelligence
instance because the SQL is tightly coupled to its schema. Each
test uses a fresh in-memory DB so they don't interfere.
"""
import json
import sqlite3
import tempfile
import time

import pytest


def _real_memory():
    from core.memory.intelligence import MemoryIntelligence
    return MemoryIntelligence(db_path=tempfile.mktemp(suffix=".db"))


def _consolidation(memory, **kwargs):
    from core.cognitive.consolidation import Consolidation
    return Consolidation(memory=memory, **kwargs)


def _raw_insert(memory, *, category, action, score=3.0, level=0,
                memory_type="episodic", timestamp=None, use_count=0,
                success_count=0):
    """Bypass MemoryIntelligence's 30s dedup by writing direct SQL."""
    conn = memory._conn()
    now = timestamp if timestamp is not None else time.time()
    cur = conn.execute(
        "INSERT INTO memories (level, memory_type, category, content, "
        "    features, action, result, score, confidence, tags, "
        "    source_ids, parent_id, timestamp, last_used, last_updated, "
        "    use_count, success_count) "
        "VALUES (?, ?, ?, '{}', '{}', ?, '{}', ?, ?, '[]', '[]', 0, ?, 0, ?, ?, ?)",
        (level, memory_type, category, action, score, score / 5.0,
         now, now, use_count, success_count),
    )
    conn.commit()
    return cur.lastrowid


def _count(memory, where="1=1"):
    return memory._conn().execute(
        f"SELECT COUNT(*) FROM memories WHERE {where}"
    ).fetchone()[0]


# ── ConsolidationReport dataclass ─────────────────────────────


class TestReport:
    def test_total_changes(self):
        from core.cognitive.consolidation import ConsolidationReport
        r = ConsolidationReport(
            deduped=2, pruned=3, rescored=1,
            patterns_extracted=4, strategies_promoted=5,
        )
        assert r.total_changes() == 15
        d = r.to_dict()
        assert d["deduped"] == 2
        assert d["strategies_promoted"] == 5


# ── Phase 1: Dedup ────────────────────────────────────────────


class TestDedup:
    def test_dedup_collapses_recent_duplicates(self):
        mem = _real_memory()
        now = time.time()
        # 4 episodes with same (category, action) within window
        for s in (4.5, 3.0, 2.5, 4.0):
            _raw_insert(mem, category="action", action="x", score=s,
                        timestamp=now - 100)
        # 1 unrelated episode
        _raw_insert(mem, category="action", action="other", score=3.0,
                    timestamp=now - 100)

        c = _consolidation(mem)
        report = c.run(prune=False, rescore=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.deduped == 3  # 4 → 1 (kept best)

        # The kept one should be the highest-scoring
        rows = mem._conn().execute(
            "SELECT score FROM memories WHERE action = 'x'",
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["score"] == 4.5

    def test_dedup_dry_run_preserves(self):
        mem = _real_memory()
        for _ in range(4):
            _raw_insert(mem, category="c", action="x")
        before = _count(mem)
        c = _consolidation(mem)
        report = c.run(prune=False, rescore=False, extract_patterns=False,
                       promote_strategies=False, dry_run=True)
        assert report.deduped == 3
        assert _count(mem) == before  # nothing actually deleted

    def test_dedup_outside_window_keeps_all(self):
        mem = _real_memory()
        old_ts = time.time() - 30 * 86400  # 30 days ago
        for _ in range(4):
            _raw_insert(mem, category="c", action="x", timestamp=old_ts)
        c = _consolidation(mem, dedup_window_s=3600)  # 1 hour window
        report = c.run(prune=False, rescore=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.deduped == 0

    def test_dedup_ignores_empty_action(self):
        mem = _real_memory()
        for _ in range(5):
            _raw_insert(mem, category="c", action="")
        c = _consolidation(mem)
        report = c.run(prune=False, rescore=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.deduped == 0


# ── Phase 2: Prune ────────────────────────────────────────────


class TestPrune:
    def test_prunes_old_low_score(self):
        mem = _real_memory()
        old = time.time() - 60 * 86400
        # Eligible: old, low score, unused
        _raw_insert(mem, category="c", action="a", score=1.0, timestamp=old)
        # Not eligible: too recent
        _raw_insert(mem, category="c", action="b", score=1.0, timestamp=time.time())
        # Not eligible: high score
        _raw_insert(mem, category="c", action="c", score=4.5, timestamp=old)
        # Not eligible: used a lot (use_count > 2)
        _raw_insert(mem, category="c", action="d", score=1.0, timestamp=old, use_count=5)

        c = _consolidation(mem, prune_age_s=30 * 86400, prune_score=1.5)
        report = c.run(dedup=False, rescore=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.pruned == 1
        assert _count(mem) == 3

    def test_prune_dry_run_keeps_all(self):
        mem = _real_memory()
        old = time.time() - 60 * 86400
        _raw_insert(mem, category="c", action="a", score=1.0, timestamp=old)
        before = _count(mem)
        c = _consolidation(mem)
        report = c.run(dedup=False, rescore=False, extract_patterns=False,
                       promote_strategies=False, dry_run=True)
        assert report.pruned == 1
        assert _count(mem) == before


# ── Phase 3: Rescore ──────────────────────────────────────────


class TestRescore:
    def test_high_success_rate_boosts_score(self):
        mem = _real_memory()
        mid = _raw_insert(mem, category="c", action="x", score=3.0,
                          use_count=10, success_count=8)  # 80% success
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.rescored == 1
        new_score = mem._conn().execute(
            "SELECT score FROM memories WHERE id = ?", (mid,),
        ).fetchone()["score"]
        assert new_score > 3.0

    def test_low_success_rate_lowers_score(self):
        mem = _real_memory()
        mid = _raw_insert(mem, category="c", action="x", score=3.0,
                          use_count=10, success_count=2)  # 20% success
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.rescored == 1
        new_score = mem._conn().execute(
            "SELECT score FROM memories WHERE id = ?", (mid,),
        ).fetchone()["score"]
        assert new_score < 3.0

    def test_mid_success_rate_no_change(self):
        mem = _real_memory()
        mid = _raw_insert(mem, category="c", action="x", score=3.0,
                          use_count=10, success_count=5)  # 50% success
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.rescored == 0

    def test_rescore_clamped_to_5(self):
        mem = _real_memory()
        mid = _raw_insert(mem, category="c", action="x", score=4.95,
                          use_count=10, success_count=10)
        c = _consolidation(mem)
        c.run(dedup=False, prune=False, extract_patterns=False,
              promote_strategies=False)
        new = mem._conn().execute(
            "SELECT score FROM memories WHERE id = ?", (mid,),
        ).fetchone()["score"]
        assert new <= 5.0

    def test_skip_low_use_count(self):
        mem = _real_memory()
        # use_count=2 → not eligible (need > 2)
        _raw_insert(mem, category="c", action="x", score=3.0,
                    use_count=2, success_count=2)
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, extract_patterns=False,
                       promote_strategies=False)
        assert report.rescored == 0


# ── Phase 4: Extract patterns ─────────────────────────────────


class TestExtractPatterns:
    def test_extracts_pattern_for_repeated_action(self):
        mem = _real_memory()
        for i in range(5):
            _raw_insert(mem, category="pricing", action="raise_price",
                        score=4.0, timestamp=time.time() - i)
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       promote_strategies=False)
        assert report.patterns_extracted == 1
        # The new pattern should be at level 1
        patterns = mem._conn().execute(
            "SELECT * FROM memories WHERE level = 1",
        ).fetchall()
        assert len(patterns) == 1
        content = json.loads(patterns[0]["content"])
        assert content["count"] == 5
        assert content["avg_score"] == 4.0

    def test_below_threshold_no_pattern(self):
        mem = _real_memory()
        for i in range(4):  # below _PATTERN_MIN_EPISODES = 5
            _raw_insert(mem, category="c", action="x", score=4.0)
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       promote_strategies=False)
        assert report.patterns_extracted == 0

    def test_existing_pattern_not_duplicated(self):
        mem = _real_memory()
        # Pre-existing pattern at level 1
        _raw_insert(mem, category="c", action="x", score=4.0, level=1)
        for _ in range(5):
            _raw_insert(mem, category="c", action="x", score=4.0)
        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       promote_strategies=False)
        assert report.patterns_extracted == 0


# ── Phase 5: Promote to strategies ───────────────────────────


class TestPromoteStrategies:
    def test_promotes_high_confidence_high_use_rule(self):
        mem = _real_memory()
        rid = mem._conn().execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            "    features, action, result, score, confidence, tags, "
            "    source_ids, parent_id, timestamp, last_used, last_updated, "
            "    use_count, success_count) "
            "VALUES (2, 'procedural', 'pricing', '{}', '{}', 'raise', '{}', "
            "    4.5, 0.9, '[]', '[]', 0, ?, 0, ?, 10, 8)",
            (time.time(), time.time()),
        ).lastrowid
        mem._conn().commit()

        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       extract_patterns=False)
        assert report.strategies_promoted == 1
        # Strategy at level 3 should now exist
        strats = mem._conn().execute(
            "SELECT * FROM memories WHERE level = 3",
        ).fetchall()
        assert len(strats) == 1
        content = json.loads(strats[0]["content"])
        assert content["promoted_from"] == rid

    def test_does_not_promote_low_confidence_rule(self):
        mem = _real_memory()
        mem._conn().execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            "    features, action, result, score, confidence, tags, "
            "    source_ids, parent_id, timestamp, last_used, last_updated, "
            "    use_count, success_count) "
            "VALUES (2, 'procedural', 'c', '{}', '{}', 'a', '{}', "
            "    3.0, 0.5, '[]', '[]', 0, ?, 0, ?, 10, 8)",
            (time.time(), time.time()),
        )
        mem._conn().commit()

        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       extract_patterns=False)
        assert report.strategies_promoted == 0

    def test_does_not_promote_low_success_rate(self):
        mem = _real_memory()
        mem._conn().execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            "    features, action, result, score, confidence, tags, "
            "    source_ids, parent_id, timestamp, last_used, last_updated, "
            "    use_count, success_count) "
            "VALUES (2, 'procedural', 'c', '{}', '{}', 'a', '{}', "
            "    3.0, 0.9, '[]', '[]', 0, ?, 0, ?, 10, 3)",
            (time.time(), time.time()),
        )
        mem._conn().commit()

        c = _consolidation(mem)
        report = c.run(dedup=False, prune=False, rescore=False,
                       extract_patterns=False)
        assert report.strategies_promoted == 0


# ── Run() defaults & error safety ─────────────────────────────


class TestRun:
    def test_no_memory_returns_empty_report(self):
        from core.cognitive.consolidation import Consolidation
        c = Consolidation(memory=None)
        report = c.run()
        assert report.total_changes() == 0
        assert any("nothing to consolidate" in n for n in report.notes)

    def test_default_run_runs_all_phases(self):
        mem = _real_memory()
        # Set up data that triggers each phase
        now = time.time()
        # Dedup target: 3 duplicates of (c, a)
        for _ in range(3):
            _raw_insert(mem, category="c", action="a", timestamp=now - 100)
        # Prune target: old + low score
        _raw_insert(mem, category="c", action="b", score=1.0,
                    timestamp=now - 60 * 86400)
        # Rescore target
        _raw_insert(mem, category="c", action="d", score=3.0,
                    use_count=10, success_count=9)
        # Pattern target: 5 same action
        for _ in range(5):
            _raw_insert(mem, category="d", action="x", score=4.0)

        c = _consolidation(mem)
        report = c.run()
        assert report.deduped > 0
        assert report.pruned > 0
        assert report.rescored > 0
        assert report.patterns_extracted > 0

    def test_dry_run_no_writes(self):
        mem = _real_memory()
        for _ in range(4):
            _raw_insert(mem, category="c", action="x")
        before = _count(mem)
        c = _consolidation(mem)
        report = c.run(dry_run=True)
        # Reports actions but doesn't write
        assert report.deduped == 3
        assert _count(mem) == before


class TestSingleton:
    def test_get_consolidation_caches(self):
        from core.cognitive import consolidation as mod
        mem = _real_memory()
        mod._instance = None
        a = mod.get_consolidation(memory=mem)
        b = mod.get_consolidation()
        assert a is b
