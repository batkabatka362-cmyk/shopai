"""Regression tests for Fix C: closed learning loop.

Pre-fix the learning pipeline recorded outcomes to memory
but **never fed them back into the next decision**:

  Decision → Action → Outcome → Learn (count) → (dead end)

``LearningPipeline._update_weights()`` just incremented an
integer and threw it away. Brain's next ``think()`` call had
no mechanism to consult accumulated learning. Core audit
flagged this as the #3 CRITICAL weakness.

Fix C introduces ``ActionWeightStore`` — a thread-safe,
SQLite-persisted EMA over ``(category, action)`` pairs — and
wires it into ``DecisionEngine._score_options`` + ``record_outcome``
so the loop actually closes:

  Decision → Action → Outcome → record_outcome
     → ActionWeightStore.record(cat, act, score)
     → EMA update
  Next decision → _score_options
     → ActionWeightStore.get(cat, act)
     → multiply final_score by learned weight

These tests pin every step of the closed loop.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def _temp_store(tmp_path):
    """Fresh in-memory-backed ActionWeightStore per test."""
    from core.learning.action_weights import (
        ActionWeightStore, reset_action_weight_store,
    )
    db_path = tmp_path / "weights.db"
    store = reset_action_weight_store(db_path)
    return store


# ── ActionWeightStore primitives ────────────────────────────


class TestActionWeightStorePrimitives:
    def test_unknown_pair_returns_neutral(self, _temp_store):
        assert _temp_store.get("pricing", "lower_10pct") == 1.0

    def test_blank_category_returns_neutral(self, _temp_store):
        assert _temp_store.get("", "x") == 1.0
        assert _temp_store.get("x", "") == 1.0

    def test_perfect_outcomes_boost_weight(self, _temp_store):
        """10 perfect outcomes should push the weight well
        above neutral but stay below the 2.0 cap."""
        weight = 1.0
        for _ in range(10):
            weight = _temp_store.record("pricing", "lower_10pct", 5.0)
        assert weight > 1.5
        assert weight <= 2.0

    def test_total_failures_suppress_weight(self, _temp_store):
        weight = 1.0
        for _ in range(10):
            weight = _temp_store.record("pricing", "raise_10pct", 0.0)
        assert weight < 0.5
        assert weight >= 0.1  # floor

    def test_neutral_outcome_drifts_toward_1(self, _temp_store):
        """Score 2.5 maps to scaled 1.0, so repeatedly
        recording should keep the weight at ~1.0."""
        weight = 1.0
        for _ in range(20):
            weight = _temp_store.record("pricing", "keep_price", 2.5)
        assert 0.95 <= weight <= 1.05

    def test_weight_clamped_to_minimum(self, _temp_store):
        """Even infinite failures can't push weight below
        the _MIN_WEIGHT floor."""
        for _ in range(500):
            _temp_store.record("x", "y", 0.0)
        assert _temp_store.get("x", "y") >= 0.1

    def test_weight_clamped_to_maximum(self, _temp_store):
        for _ in range(500):
            _temp_store.record("x", "y", 5.0)
        assert _temp_store.get("x", "y") <= 2.0

    def test_score_out_of_range_is_clamped(self, _temp_store):
        """Defensive: score outside [0, 5] is clamped."""
        w1 = _temp_store.record("pricing", "x", 999.0)  # clamps to 5
        _temp_store.reset("pricing")
        w2 = _temp_store.record("pricing", "x", 5.0)
        assert abs(w1 - w2) < 0.001

        _temp_store.reset("pricing")
        w3 = _temp_store.record("pricing", "x", -999.0)  # clamps to 0
        _temp_store.reset("pricing")
        w4 = _temp_store.record("pricing", "x", 0.0)
        assert abs(w3 - w4) < 0.001

    def test_persistence_across_store_reload(self, tmp_path):
        """Weights written by one instance must be readable
        by a fresh instance pointing at the same DB."""
        from core.learning.action_weights import (
            reset_action_weight_store,
        )
        db_path = tmp_path / "weights.db"
        store1 = reset_action_weight_store(db_path)
        for _ in range(5):
            store1.record("pricing", "lower_10pct", 5.0)
        w_before = store1.get("pricing", "lower_10pct")

        # Reload
        store2 = reset_action_weight_store(db_path)
        w_after = store2.get("pricing", "lower_10pct")
        assert abs(w_before - w_after) < 0.001

    def test_reset_category_drops_only_that_category(self, _temp_store):
        _temp_store.record("pricing", "a", 5.0)
        _temp_store.record("marketing", "b", 5.0)
        _temp_store.reset("pricing")
        assert _temp_store.get("pricing", "a") == 1.0
        assert _temp_store.get("marketing", "b") > 1.0

    def test_snapshot_returns_every_entry(self, _temp_store):
        _temp_store.record("pricing", "a", 5.0)
        _temp_store.record("pricing", "b", 0.0)
        snap = _temp_store.snapshot()
        assert "pricing:a" in snap
        assert "pricing:b" in snap
        assert snap["pricing:a"]["samples"] == 1
        assert snap["pricing:b"]["samples"] == 1

    def test_stats_reflects_total_samples(self, _temp_store):
        for _ in range(3):
            _temp_store.record("pricing", "a", 5.0)
        for _ in range(2):
            _temp_store.record("marketing", "b", 3.0)
        stats = _temp_store.stats()
        assert stats["entries"] == 2
        assert stats["total_samples"] == 5


# ── DecisionEngine weight integration ───────────────────────


class TestDecisionEngineConsultsWeights:
    def _make_engine_with_temp_store(self, tmp_path):
        """Build a DecisionEngine whose weight store points
        at a disposable SQLite file."""
        from core.learning.action_weights import reset_action_weight_store
        from core.brain.decision_engine import DecisionEngine
        db_path = tmp_path / "engine_weights.db"
        reset_action_weight_store(db_path)
        return DecisionEngine()

    def test_decide_returns_decision_with_score(self, tmp_path):
        engine = self._make_engine_with_temp_store(tmp_path)
        result = engine.decide("pricing", {"price": 50, "cost": 20})
        # Should return a valid Decision object
        assert result.choice is not None
        assert result.score >= 0
        assert result.category == "pricing"

    def test_score_options_includes_learned_weight(self, tmp_path):
        """Every scored option should carry a ``learned_weight``
        field so operators can audit why ranking changed."""
        engine = self._make_engine_with_temp_store(tmp_path)
        context = {"best_cases": [], "failures": [], "rules": [],
                   "intel_rules": [], "total_memories": 0}
        options = [
            {"action": "keep_price", "reason": "x", "profit_score": 0.5, "risk_score": 0.1},
            {"action": "lower_10pct", "reason": "x", "profit_score": 0.4, "risk_score": 0.3},
        ]
        scored = engine._score_options(options, context, {}, category="pricing")
        for s in scored:
            assert "learned_weight" in s
            assert "base_score" in s
            # No learned history → weight is neutral 1.0
            assert s["learned_weight"] == 1.0

    def test_boosted_action_beats_neutral_option(self, tmp_path):
        """THE key loop closure: record many successful
        outcomes for one action, then call decide with two
        options (one boosted, one neutral) and verify the
        boosted action wins."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)

        # Bake in a strong positive history for "lower_10pct"
        # in the pricing category.
        store = get_action_weight_store()
        for _ in range(20):
            store.record("pricing", "lower_10pct", 5.0)

        # Now ask the engine to score both options manually.
        context = {"best_cases": [], "failures": [], "rules": [],
                   "intel_rules": [], "total_memories": 0}
        options = [
            # Give keep_price a HIGHER base (higher profit,
            # lower risk) so without learning it would win.
            {"action": "keep_price", "reason": "x", "profit_score": 0.8, "risk_score": 0.05},
            # lower_10pct has a worse base.
            {"action": "lower_10pct", "reason": "x", "profit_score": 0.4, "risk_score": 0.4},
        ]
        scored = engine._score_options(
            options, context, {}, category="pricing",
        )
        by_action = {s["action"]: s for s in scored}
        keep = by_action["keep_price"]
        lower = by_action["lower_10pct"]

        # Before learning: keep_price would win (base score)
        assert keep["base_score"] > lower["base_score"]
        # After learning: lower_10pct weight > 1.5 pushes it
        # past keep_price's unboosted score.
        assert lower["learned_weight"] > 1.5
        assert lower["final_score"] > keep["final_score"], (
            f"learned boost failed to flip ranking: "
            f"keep={keep}, lower={lower}"
        )

    def test_suppressed_action_loses_to_neutral(self, tmp_path):
        """Mirror of the above: bake in a strong FAILURE
        history for an action and verify it falls below a
        neutral-weight option."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)

        store = get_action_weight_store()
        for _ in range(20):
            store.record("pricing", "raise_10pct", 0.0)

        context = {"best_cases": [], "failures": [], "rules": [],
                   "intel_rules": [], "total_memories": 0}
        options = [
            {"action": "keep_price", "reason": "x", "profit_score": 0.5, "risk_score": 0.2},
            # Same base numbers so only the learned weight differs.
            {"action": "raise_10pct", "reason": "x", "profit_score": 0.5, "risk_score": 0.2},
        ]
        scored = engine._score_options(
            options, context, {}, category="pricing",
        )
        by_action = {s["action"]: s for s in scored}
        assert by_action["raise_10pct"]["learned_weight"] < 0.5
        assert by_action["raise_10pct"]["final_score"] < by_action["keep_price"]["final_score"]

    def test_record_outcome_updates_weight_store(self, tmp_path):
        """``DecisionEngine.record_outcome`` must write to
        the weight store so future calls see the update."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)

        store = get_action_weight_store()
        # Start neutral
        assert store.get("pricing", "lower_10pct") == 1.0

        # Record a perfect outcome
        engine.record_outcome(
            category="pricing",
            action="lower_10pct",
            input_data={"price": 50},
            result={"success": True},
            score=5.0,
        )

        # Weight should have moved toward the positive end
        w = store.get("pricing", "lower_10pct")
        assert w > 1.0

    def test_record_outcome_multiple_outcomes_ema(self, tmp_path):
        """Sequential record_outcome calls produce a smooth
        EMA — NOT step-change behaviour."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)
        store = get_action_weight_store()

        weights_over_time = []
        for _ in range(10):
            engine.record_outcome(
                category="pricing",
                action="lower_10pct",
                input_data={},
                result={},
                score=5.0,
            )
            weights_over_time.append(
                store.get("pricing", "lower_10pct"),
            )

        # Monotonic increase
        for a, b in zip(weights_over_time, weights_over_time[1:]):
            assert b >= a
        # Smoothing: after 10 perfect outcomes, still below 2.0
        # (would take ~22 to saturate)
        assert weights_over_time[-1] < 2.0
        # But clearly above 1.0
        assert weights_over_time[-1] > 1.5

    def test_record_outcome_with_missing_category_or_action_is_safe(self, tmp_path):
        """Defensive: recording with blank category/action
        must not crash or pollute the store."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)
        store = get_action_weight_store()

        engine.record_outcome("", "action", {}, {}, 5.0)
        engine.record_outcome("pricing", "", {}, {}, 5.0)

        # Neither should have landed in the store
        stats = store.stats()
        assert stats["entries"] == 0

    def test_weight_store_failure_does_not_break_record_outcome(self, tmp_path, monkeypatch):
        """If the weight store raises during record, the
        memory write still happens — the loop closure is
        fail-soft."""
        from core.learning.action_weights import get_action_weight_store
        engine = self._make_engine_with_temp_store(tmp_path)
        store = get_action_weight_store()

        def _boom(*args, **kwargs):
            raise RuntimeError("weight store crash")

        monkeypatch.setattr(store, "record", _boom)

        # Must not raise
        engine.record_outcome(
            category="pricing",
            action="lower_10pct",
            input_data={"price": 50},
            result={"success": True},
            score=5.0,
        )


# ── End-to-end learning loop ────────────────────────────────


class TestLearningLoopEndToEnd:
    def test_outcome_updates_weight_store_end_to_end(self, tmp_path):
        """End-to-end closure test for Fix C.

        Scenario:
          1. Start fresh (empty weight store at a tmp path).
          2. Build a DecisionEngine that uses the fresh store.
          3. Record 30 failures of ``pricing / lower_10pct``
             via ``record_outcome``.
          4. Directly query the weight store for the learned
             weight of that pair.
          5. Verify the weight dropped well below 1.0 —
             this is the proof that the outcome → weight
             step of the loop closes.
          6. Call ``_score_options`` with a ``lower_10pct``
             candidate and verify the learned weight is
             multiplied into the final score.

        Pre-fix there was no weight store at all: step 4
        would have had no data to query, and the score in
        step 6 would have ignored learning entirely.

        The test deliberately avoids relying on
        ``engine.decide`` end-to-end because that method also
        touches the shared brain_memory SQLite which is
        polluted by earlier test runs in the same pytest
        session. We test the loop closure directly via
        ``record_outcome`` + ``_score_options``, which is
        exactly the contract Fix C establishes.
        """
        from core.learning.action_weights import reset_action_weight_store
        db_path = tmp_path / "e2e_weights.db"
        store = reset_action_weight_store(db_path)

        from core.brain.decision_engine import DecisionEngine
        engine = DecisionEngine()

        # Sanity: the fresh store starts neutral
        assert store.get("pricing", "lower_10pct") == 1.0

        # Step 3: record 30 failures
        for _ in range(30):
            engine.record_outcome(
                category="pricing",
                action="lower_10pct",
                input_data={"price": 50.0, "cost": 15.0},
                result={"success": False},
                score=0.0,
            )

        # Step 4: weight store has learned the failure
        learned = store.get("pricing", "lower_10pct")
        assert learned < 0.5, (
            f"weight did not drop after 30 failures: {learned}"
        )

        # Step 5: verify the score path actually consults
        # the learned weight.
        context = {
            "best_cases": [], "failures": [], "rules": [],
            "intel_rules": [], "total_memories": 0,
        }
        options = [
            {"action": "lower_10pct", "reason": "x",
             "profit_score": 0.8, "risk_score": 0.1},
        ]
        scored = engine._score_options(
            options, context, {}, category="pricing",
        )
        lower = scored[0]
        assert lower["learned_weight"] == pytest.approx(learned, abs=0.001)
        assert lower["final_score"] == pytest.approx(
            lower["base_score"] * learned, abs=0.01,
        )
        # Without learning this option would be well above 0.5,
        # but the 0.1-ish weight crushes it.
        assert lower["final_score"] < lower["base_score"]

    def test_positive_reinforcement_loop(self, tmp_path):
        """Mirror test: 30 successful outcomes should push
        the option's final_score ABOVE its base_score (the
        learned weight exceeds 1.0)."""
        from core.learning.action_weights import reset_action_weight_store
        db_path = tmp_path / "e2e_pos.db"
        store = reset_action_weight_store(db_path)

        from core.brain.decision_engine import DecisionEngine
        engine = DecisionEngine()

        for _ in range(30):
            engine.record_outcome(
                category="pricing",
                action="lower_10pct",
                input_data={},
                result={"success": True},
                score=5.0,
            )

        learned = store.get("pricing", "lower_10pct")
        assert learned > 1.5, (
            f"weight did not rise after 30 successes: {learned}"
        )

        context = {
            "best_cases": [], "failures": [], "rules": [],
            "intel_rules": [], "total_memories": 0,
        }
        options = [{
            "action": "lower_10pct", "reason": "x",
            "profit_score": 0.4, "risk_score": 0.2,
        }]
        scored = engine._score_options(
            options, context, {}, category="pricing",
        )
        assert scored[0]["final_score"] > scored[0]["base_score"]
