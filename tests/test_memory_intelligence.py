"""Tests for MemoryIntelligence — written to cover bugs found in
the data-flow audit:

  1. The three promotion-INSERTs (events→pattern, pattern→rule,
     rule→strategy) must include a populated `result` column.
     Previously they omitted it and silently relied on the schema
     default `'{}'`, leaving high-level memories without provenance.
  2. retrieve() with a tag filter previously fetched `limit*2`
     rows and filtered in Python, so when the top-scored rows did
     not match any wanted tag the caller silently received fewer
     than `limit` results. Tag filtering is now pushed into SQL.
"""
import json
import tempfile
import time

import pytest


def _fresh_memory():
    from core.memory.intelligence import MemoryIntelligence
    return MemoryIntelligence(db_path=tempfile.mktemp(suffix=".db"))


def _seed_events(mem, category, action, *, n, score=4.0, tags=None):
    """Bypass the 30s create()-dedup by writing rows directly so a
    test can stage many events instantly."""
    conn = mem._conn()
    now = time.time()
    for i in range(n):
        conn.execute(
            "INSERT INTO memories (level, memory_type, category, content, "
            " features, action, result, score, confidence, tags, "
            " evidence_count, source_ids, timestamp, last_updated) "
            "VALUES (0, 'episodic', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                category,
                json.dumps({"i": i}),
                json.dumps({"feat": "x"}),
                action,
                json.dumps({"k": "v"}),
                score,
                score / 5.0,
                json.dumps(tags or [category, action]),
                1,
                json.dumps([]),
                now - i,
                now,
            ),
        )
    conn.commit()


# ── Promotion INSERTs include `result` ───────────────────────


class TestPromotionResultColumn:
    def test_pattern_promotion_writes_structured_result(self):
        mem = _fresh_memory()
        _seed_events(mem, "pricing", "raise_price", n=6)
        mem._promote_events_to_pattern("pricing")

        rows = mem._conn().execute(
            "SELECT result FROM memories WHERE level = 1"
        ).fetchall()
        assert len(rows) == 1
        result = json.loads(rows[0]["result"])
        assert result["promoted_from"] == "events"
        assert result["source_count"] == 6
        assert "avg_score" in result

    def test_rule_promotion_writes_structured_result(self):
        mem = _fresh_memory()
        _seed_events(mem, "ads", "boost_budget", n=8, score=4.5)
        mem._promote_events_to_pattern("ads")
        # Patterns need evidence_count >= rule threshold to promote.
        # Force the pattern's evidence_count high enough.
        mem._conn().execute(
            "UPDATE memories SET evidence_count = 20, score = 4.5 "
            "WHERE level = 1"
        )
        mem._conn().commit()
        mem._promote_patterns_to_rules("ads")

        rows = mem._conn().execute(
            "SELECT result FROM memories WHERE level = 2"
        ).fetchall()
        assert len(rows) >= 1
        result = json.loads(rows[0]["result"])
        assert result["promoted_from"] == "pattern"
        assert "parent_id" in result
        assert "evidence_count" in result

    def test_strategy_promotion_writes_structured_result(self):
        mem = _fresh_memory()
        # Pre-seed enough qualifying rules directly.
        conn = mem._conn()
        now = time.time()
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                " features, action, result, score, confidence, tags, "
                " evidence_count, use_count, success_count, source_ids, "
                " timestamp, last_updated) "
                "VALUES (2, 'procedural', 'inv', ?, ?, ?, '{}', ?, ?, ?, "
                " ?, ?, ?, ?, ?, ?)",
                (
                    json.dumps({"r": i}),
                    json.dumps({"f": "x"}),
                    f"rule_{i}",
                    4.6, 0.92,
                    json.dumps(["inv", "rule"]),
                    20, 25, 23,
                    json.dumps([]),
                    now, now,
                ),
            )
        conn.commit()
        mem._promote_rules_to_strategies("inv")

        rows = mem._conn().execute(
            "SELECT result FROM memories WHERE level = 3"
        ).fetchall()
        assert len(rows) >= 1
        result = json.loads(rows[0]["result"])
        assert result["promoted_from"] == "rules"
        assert result["rule_count"] >= 1


# ── retrieve() tag-filter undercount ─────────────────────────


class TestRetrieveTagFilter:
    def test_top_scored_rows_dont_match_tags_still_returns_limit(self):
        """Regression: previously fetched limit*2 high-scored rows
        then python-filtered by tags. If none of the top-scored
        rows had the wanted tag, the caller got 0 results even
        though the database had plenty of matches at lower scores.
        Now SQL pre-filters by tag so the LIMIT applies to *matching*
        rows only."""
        mem = _fresh_memory()
        # 20 high-scored "noise" rows with tag "irrelevant"
        _seed_events(mem, "x", "noise", n=20, score=5.0, tags=["irrelevant"])
        # 5 lower-scored rows with the wanted tag
        _seed_events(mem, "x", "wanted", n=5, score=3.5, tags=["wanted"])

        results = mem.retrieve("x", tags=["wanted"], limit=5)
        assert len(results) == 5
        for r in results:
            assert "wanted" in r["tags"]

    def test_no_tag_filter_unchanged(self):
        mem = _fresh_memory()
        _seed_events(mem, "x", "a", n=5, score=4.0, tags=["a"])
        results = mem.retrieve("x", limit=10)
        assert len(results) == 5

    def test_multi_tag_or_semantics(self):
        mem = _fresh_memory()
        _seed_events(mem, "x", "a", n=3, score=4.0, tags=["a"])
        _seed_events(mem, "x", "b", n=3, score=4.0, tags=["b"])
        _seed_events(mem, "x", "c", n=3, score=4.0, tags=["c"])
        results = mem.retrieve("x", tags=["a", "b"], limit=10)
        assert len(results) == 6
        kinds = {r["action"] for r in results}
        assert kinds == {"a", "b"}

    def test_unknown_tag_returns_empty(self):
        mem = _fresh_memory()
        _seed_events(mem, "x", "a", n=5, score=4.0, tags=["a"])
        assert mem.retrieve("x", tags=["nope"], limit=10) == []

    def test_substring_tag_does_not_false_match(self):
        # The SQL LIKE clause uses '%"<tag>"%' so a tag like "a"
        # must not match a different tag "abc". The Python re-filter
        # is the second line of defense.
        mem = _fresh_memory()
        _seed_events(mem, "x", "y", n=5, score=4.0, tags=["abc"])
        results = mem.retrieve("x", tags=["a"], limit=10)
        assert results == []

    def test_empty_tag_list_skipped(self):
        # Defensive: empty/None tags inside the list are dropped.
        mem = _fresh_memory()
        _seed_events(mem, "x", "y", n=3, score=4.0, tags=["good"])
        # An empty string should not turn into LIKE '%""%'
        results = mem.retrieve("x", tags=["", "good"], limit=10)
        assert len(results) == 3
