"""Tests for audit-pass-12 fixes in core/brain/memory.py.

  1. _extract_features() called raw `float(data.get("price"))` so
     a string price like "$10.99" or "" raised ValueError and the
     entire feature extractor crashed mid-cycle, propagating out
     of `record_decision` / `ingest`.
  2. _detect_patterns() and _generate_rule() did check-then-write
     against patterns / rules tables with no UNIQUE constraint,
     so two threads racing on the same pattern_str could both
     INSERT and produce duplicate rows.
  3. get_rules() handed callers the cached list directly. Any
     mutation to the returned list or its dicts poisoned every
     subsequent reader of the same cache entry.
"""
import tempfile
import threading

import pytest


def _fresh_brain():
    from core.brain.memory import IntelligentMemory
    return IntelligentMemory(tempfile.mktemp(suffix=".db"))


# ── _extract_features safe-numeric ───────────────────────────


class TestExtractFeaturesSafeNumeric:
    def test_string_price_does_not_crash(self):
        """Regression: previously `float("$10.99")` raised
        ValueError and propagated out of record_decision."""
        brain = _fresh_brain()
        # Should not raise
        mid = brain.record_decision(
            "pricing",
            input_data={"price": "$10.99", "cost": "5.00"},
            action="raise",
            result={"ok": True},
            score=4.0,
        )
        assert mid > 0

    def test_empty_string_numeric_does_not_crash(self):
        brain = _fresh_brain()
        mid = brain.record_decision(
            "pricing",
            input_data={"price": "", "cost": ""},
            action="x",
            result={},
            score=3.0,
        )
        assert mid > 0

    def test_string_customer_orders_does_not_crash(self):
        brain = _fresh_brain()
        mid = brain.record_decision(
            "customer",
            input_data={"orders": "5", "total_spent": "120.50"},
            action="upsell",
            result={},
            score=3.5,
        )
        assert mid > 0

    def test_valid_numeric_still_extracts_margin(self):
        from core.brain.memory import IntelligentMemory
        features = IntelligentMemory._extract_features(
            "pricing", {"price": 50, "cost": 20},
        )
        assert features["has_price"] is True
        assert features["has_cost"] is True
        assert "margin" in features
        assert features["price_tier"] == "premium"


# ── Pattern + rule UNIQUE indexes via UPSERT ────────────────


class TestPatternRuleUniqueness:
    def test_repeated_detect_patterns_no_duplicates(self):
        """The v2 UNIQUE index on patterns.pattern + atomic UPSERT
        means feeding the same features 10 times produces exactly
        ONE row, not 10."""
        brain = _fresh_brain()
        for _ in range(10):
            brain._detect_patterns(
                "pricing",
                {"feat_a": "high", "feat_b": "low"},
                score=4.0,
            )
        rows = brain._conn().execute(
            "SELECT pattern, frequency FROM patterns"
        ).fetchall()
        # Exactly one pattern row exists.
        assert len(rows) == 1
        # Frequency tracks the 10 calls.
        assert rows[0]["frequency"] == 10

    def test_concurrent_detect_patterns_no_duplicates(self):
        """Two threads racing on the same pattern_str must both
        succeed without creating duplicate rows."""
        brain = _fresh_brain()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(20):
                    brain._detect_patterns(
                        "pricing", {"feat_a": "high"}, score=4.5,
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        rows = brain._conn().execute(
            "SELECT pattern, frequency FROM patterns"
        ).fetchall()
        # Still exactly one pattern row regardless of race.
        assert len(rows) == 1
        # Frequency totals all 80 events (4 threads * 20 each).
        assert rows[0]["frequency"] == 80

    def test_repeated_generate_rule_no_duplicates(self):
        brain = _fresh_brain()
        for _ in range(5):
            brain._generate_rule("pricing", "x→good", 4.5)
        rows = brain._conn().execute("SELECT rule FROM rules").fetchall()
        assert len(rows) == 1

    def test_generate_rule_only_bumps_cache_gen_on_real_insert(self):
        brain = _fresh_brain()
        brain._generate_rule("pricing", "x→good", 4.5)
        gen_after_first = brain._rules_cache_gen
        # Second call is a no-op (rule already exists)
        brain._generate_rule("pricing", "x→good", 4.5)
        assert brain._rules_cache_gen == gen_after_first

    def test_pattern_to_rule_promotion_still_fires(self):
        """End-to-end: feeding the same features 3+ times must
        still promote a pattern to a rule even after the UPSERT
        refactor."""
        brain = _fresh_brain()
        for _ in range(3):
            brain._detect_patterns(
                "pricing", {"feat_a": "high", "feat_b": "high"}, score=4.5,
            )
        rules = brain._conn().execute("SELECT * FROM rules").fetchall()
        assert len(rules) >= 1


# ── get_rules cache returns defensive copy ───────────────────


class TestGetRulesDefensiveCopy:
    def test_cache_hit_returns_distinct_object(self):
        brain = _fresh_brain()
        first = brain.get_rules("pricing")
        second = brain.get_rules("pricing")
        assert first == second
        assert first is not second

    def test_caller_mutation_does_not_poison_cache(self):
        brain = _fresh_brain()
        # Inject a real rule so the cache isn't just an empty list.
        brain._generate_rule("pricing", "low_margin→bad", 1.5)
        first = brain.get_rules("pricing")
        assert len(first) == 1
        first[0]["mutated"] = "yes"
        first.clear()
        # Subsequent reads see the original cached state.
        second = brain.get_rules("pricing")
        assert len(second) == 1
        assert "mutated" not in second[0]

    def test_cache_invalidation_on_new_rule_still_works(self):
        brain = _fresh_brain()
        brain.get_rules("pricing")  # prime
        gen_before = brain._rules_cache_gen
        brain._generate_rule("pricing", "y→good", 4.5)
        assert brain._rules_cache_gen > gen_before
        rules = brain.get_rules("pricing")
        assert len(rules) == 1
