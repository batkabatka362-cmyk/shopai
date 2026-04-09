"""Regression tests for Fix P: exploration boost signal
actually influences decision ranking.

Pre-fix, ``ExplorationBoost.record(action)`` ran after
every ``brain.think()`` in ``AutonomousController.run_cycle``
phase 1b, and ``should_explore()`` correctly detected when
the same action dominated the last 10 cycles — but the
signal was never read anywhere. No downstream code
diversified or dampened decisions when
``should_explore().explore == True``. The repetition
detector existed but was advisory-only.

Core audit wave-3 flagged this as the #2 MEDIUM weakness.
Fix P makes ``DecisionBrain._decide`` consult
``ExplorationBoost`` at the end of the ranking pass:

  1. If ``should_explore()["explore"]`` is True, decisions
     whose ``type`` matches ``most_common`` get their score
     multiplied by 0.7 (a 30% dampener).
  2. The dampener emits an ``exploration_dampener``
     attribution entry so operators can trace why the
     brain picked a different action this cycle.
  3. When exploration is NOT needed (diversity is fine),
     no dampener is applied — existing behavior preserved.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def reset_exploration_singleton():
    """Reset the ExplorationBoost singleton before each
    test so history doesn't leak between runs."""
    import core.brain.smart_rotation as sr
    sr._explore = None
    yield
    sr._explore = None


class TestExplorationSignalReadByDecide:
    def test_no_exploration_when_diversity_high(self, reset_exploration_singleton):
        """Baseline: diverse action history → should_explore
        returns False → no dampener applied."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        from core.brain.smart_rotation import get_exploration_boost

        eb = get_exploration_boost()
        for a in ["add_images", "lower_price", "raise_price",
                  "add_products", "campaign", "add_images",
                  "lower_price", "raise_price", "add_products", "campaign"]:
            eb.record(a)

        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]
        decisions = brain._decide(state, problems, [], {})
        dec = decisions[0]
        # No exploration_dampener attribution because
        # should_explore == False
        sources = [a.get("source") for a in dec.get("attribution", [])]
        assert "exploration_dampener" not in sources

    def test_repetitive_action_dampened(self, reset_exploration_singleton):
        """Push the history to >70% same action → the brain
        must dampen that action's score on the next
        _decide() call."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        from core.brain.smart_rotation import get_exploration_boost

        eb = get_exploration_boost()
        # 8/10 are the same → repetition rate 0.8, dominates
        for _ in range(8):
            eb.record("add_images")
        eb.record("lower_price")
        eb.record("raise_price")

        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})

        # Baseline: a problem producing add_images as the
        # critical decision. Without Fix P, this would win
        # despite being the repetitive action.
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
            {"action": "lower_price", "severity": "high",
             "detail": "margin squeeze"},
        ]
        decisions = brain._decide(state, problems, [], {})
        add_img = next(d for d in decisions if d["type"] == "add_images")
        lower = next(d for d in decisions if d["type"] == "lower_price")

        # add_images should carry an exploration_dampener
        sources = [a.get("source") for a in add_img.get("attribution", [])]
        assert "exploration_dampener" in sources, (
            f"expected exploration_dampener on the repetitive "
            f"action, got {add_img.get('attribution')}"
        )

        # lower_price should NOT have one (not repetitive)
        lower_sources = [a.get("source") for a in lower.get("attribution", [])]
        assert "exploration_dampener" not in lower_sources

    def test_dampener_reduces_score(self, reset_exploration_singleton):
        """When the dampener fires, the score must actually
        be lower than the baseline (no-dampener) case."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        from core.brain.smart_rotation import get_exploration_boost

        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]

        # Baseline: empty history
        baseline = brain._decide(state, problems, [], {})
        baseline_score = baseline[0]["score"]

        # Now poison the history
        eb = get_exploration_boost()
        for _ in range(8):
            eb.record("add_images")
        eb.record("lower_price")
        eb.record("raise_price")

        dampened = brain._decide(state, problems, [], {})
        dampened_score = dampened[0]["score"]

        assert dampened_score < baseline_score, (
            f"dampener should reduce score "
            f"(baseline={baseline_score}, dampened={dampened_score})"
        )

    def test_attribution_entry_shape(self, reset_exploration_singleton):
        from core.brain.decision_brain import DecisionBrain, StoreState
        from core.brain.smart_rotation import get_exploration_boost

        eb = get_exploration_boost()
        for _ in range(9):
            eb.record("repeat_me")
        eb.record("other")

        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})
        problems = [
            {"action": "repeat_me", "severity": "high",
             "detail": "test"},
        ]
        decisions = brain._decide(state, problems, [], {})
        d = decisions[0]
        entry = next(
            (a for a in d["attribution"]
             if a.get("source") == "exploration_dampener"),
            None,
        )
        assert entry is not None
        assert entry["rule_id"] == "exploration:repeat_me"
        assert entry["impact"] < 0
        assert isinstance(entry["description"], str)


class TestExistingBehaviorPreserved:
    """Fix P must not over-dampen when there's no repetition."""

    def test_empty_history_no_dampener(self, reset_exploration_singleton):
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})
        problems = [
            {"action": "x", "severity": "high", "detail": "y"},
        ]
        decisions = brain._decide(state, problems, [], {})
        for d in decisions:
            sources = [a.get("source") for a in d.get("attribution", [])]
            assert "exploration_dampener" not in sources

    def test_small_history_no_dampener(self, reset_exploration_singleton):
        """<10 records → should_explore returns insufficient_data."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        from core.brain.smart_rotation import get_exploration_boost

        eb = get_exploration_boost()
        for _ in range(5):
            eb.record("x")

        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({"products": [], "orders": [], "customers": []})
        problems = [{"action": "x", "severity": "high", "detail": "y"}]
        decisions = brain._decide(state, problems, [], {})
        sources = [a.get("source") for a in decisions[0].get("attribution", [])]
        assert "exploration_dampener" not in sources
