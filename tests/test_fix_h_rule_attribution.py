"""Regression tests for Fix H: rule attribution in decisions.

Pre-fix, ``DecisionEngine.decide()`` set ``rules_applied`` to
the top 3 rules from ``context.get("rules", [])`` — but these
were the RETRIEVED rules, NOT the ones that actually
influenced the score. Two problems:

  1. If the winning option happened to NOT match any rule,
     the ``rules_applied`` list still showed 3 rules, giving
     the false impression that those rules caused the choice.
  2. The list contained only 60-char rule text fragments —
     no structured data on WHICH rule fired, HOW MUCH it
     shifted the score, or WHAT source (L5 rules vs L2
     intel rules vs memory best_cases vs learned weights vs
     goal weights).

``DecisionBrain._decide()`` had zero attribution at all. The
audit flagged this as the #11 MEDIUM weakness: "no rule
attribution in decisions — operators can't explain WHY the
system made a decision, only WHAT it decided."

Fix H adds structured attribution:

  * ``Decision.attribution`` — list of ``{source, rule_id,
    description, impact}`` dicts capturing every rule,
    memory case, learned weight, and goal weight that
    actually shifted the WINNING option's score.
  * Each brain decision dict in ``thought["decisions"]``
    carries an ``attribution`` field explaining the
    priority-rule source and goal-weight contribution.
  * ``rules_applied`` is kept for backwards compat but is
    now DERIVED from the attribution list of the actual
    winning option (not from unrelated context rules).
"""
from __future__ import annotations

import pytest


class TestDecisionEngineAttributionShape:
    """Basic shape: Decision objects expose an ``attribution``
    list, and ``to_dict`` serialises it."""

    def test_decision_object_has_attribution_field(self):
        from core.brain.decision_engine import Decision
        d = Decision(
            choice="keep_price", reason="ok", score=0.5,
            category="pricing",
        )
        assert hasattr(d, "attribution")
        assert isinstance(d.attribution, list)

    def test_to_dict_includes_attribution(self):
        from core.brain.decision_engine import Decision
        d = Decision(
            choice="keep_price", reason="ok", score=0.5,
            category="pricing",
            attribution=[{
                "source": "memory_best_case", "rule_id": "bc1",
                "description": "worked before", "impact": 0.1,
            }],
        )
        out = d.to_dict()
        assert "attribution" in out
        assert out["attribution"][0]["source"] == "memory_best_case"


class TestDecisionEngineAttributionFromScoring:
    """When an option wins with a rule boost, that rule must
    appear in the attribution with the correct impact.

    These tests exercise ``_score_options`` DIRECTLY with
    controlled context so they're not coupled to the shared
    brain memory state that accumulates across the full
    test suite.
    """

    def test_learned_weight_attribution_when_nonneutral(self, tmp_path):
        """Seed the ActionWeightStore so ``raise_10pct`` has
        a strong learned weight, then verify the scored
        option's attribution carries a ``learned_weight``
        entry."""
        from core.learning.action_weights import (
            get_action_weight_store, reset_action_weight_store,
        )
        reset_action_weight_store(tmp_path / "w.db")
        store = get_action_weight_store()
        for _ in range(15):
            store.record("pricing", "raise_10pct", 5.0)

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "raise_10pct", "reason": "r", "profit_score": 0.6, "risk_score": 0.3},
        ]
        scored = eng._score_options(
            options, {"total_memories": 0}, {"price": 100, "cost": 40},
            category="pricing",
        )
        entry = scored[0]
        sources = {a["source"] for a in entry["attribution"]}
        assert "learned_weight" in sources, (
            f"expected learned_weight attribution, got {entry['attribution']}"
        )
        lw = [a for a in entry["attribution"] if a["source"] == "learned_weight"][0]
        assert isinstance(lw["impact"], (int, float))
        assert lw["rule_id"] == "history:pricing:raise_10pct"
        # The weight should be meaningfully above neutral
        assert entry["learned_weight"] > 1.1

    def test_no_learned_weight_attribution_when_neutral(self, tmp_path):
        """When the weight store is empty, the learned weight
        is exactly 1.0 and no ``learned_weight`` entry should
        be emitted (to avoid polluting the trail with
        zero-impact rows)."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "keep_price", "reason": "r", "profit_score": 0.5, "risk_score": 0.3},
        ]
        scored = eng._score_options(
            options, {"total_memories": 0}, {"price": 100, "cost": 50},
            category="pricing",
        )
        sources = {a["source"] for a in scored[0]["attribution"]}
        assert "learned_weight" not in sources, (
            "learned_weight entry must be omitted when the "
            "weight is neutral (1.0) — it's noise"
        )

    def test_memory_best_case_attribution(self, tmp_path):
        """A ``best_cases`` entry for the winning action must
        produce a ``memory_best_case`` attribution entry."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "lower_10pct", "reason": "r", "profit_score": 0.55, "risk_score": 0.4},
        ]
        context = {
            "total_memories": 0,
            "best_cases": [{"action": "lower_10pct", "score": 4.7}],
        }
        scored = eng._score_options(
            options, context, {"price": 100, "cost": 50},
            category="pricing",
        )
        sources = [a["source"] for a in scored[0]["attribution"]]
        assert "memory_best_case" in sources
        bc = [a for a in scored[0]["attribution"] if a["source"] == "memory_best_case"][0]
        assert bc["impact"] == 0.1
        assert bc["rule_id"] == "best_case:lower_10pct"

    def test_memory_failure_attribution(self, tmp_path):
        """A ``failures`` entry for the winning action must
        produce a ``memory_failure`` attribution entry with
        negative impact."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "lower_10pct", "reason": "r", "profit_score": 0.55, "risk_score": 0.4},
        ]
        context = {
            "total_memories": 0,
            "failures": [{"action": "lower_10pct", "score": 1.3}],
        }
        scored = eng._score_options(
            options, context, {"price": 100, "cost": 50},
            category="pricing",
        )
        sources = [a["source"] for a in scored[0]["attribution"]]
        assert "memory_failure" in sources
        mf = [a for a in scored[0]["attribution"] if a["source"] == "memory_failure"][0]
        assert mf["impact"] < 0
        assert mf["rule_id"] == "failure:lower_10pct"

    def test_l5_rule_prefer_attribution(self, tmp_path):
        """An L5 rules entry with ``action='prefer'`` and a
        condition that contains the option action must
        produce a ``rules_L5`` attribution entry with
        positive impact."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "raise_10pct", "reason": "r", "profit_score": 0.5, "risk_score": 0.3},
        ]
        context = {
            "total_memories": 0,
            "rules": [{
                "id": "R-42",
                "action": "prefer",
                "condition": "when margin low prefer raise_10pct",
                "confidence": 0.8,
                "rule": "prefer raise_10pct when margin low",
            }],
        }
        scored = eng._score_options(
            options, context, {"price": 100, "cost": 40},
            category="pricing",
        )
        entries = [a for a in scored[0]["attribution"] if a["source"] == "rules_L5"]
        assert entries, (
            f"expected rules_L5 attribution, got {scored[0]['attribution']}"
        )
        r = entries[0]
        assert r["rule_id"] == "R-42"
        assert r["impact"] > 0

    def test_l5_rule_avoid_attribution(self, tmp_path):
        """An L5 rules entry with ``action='avoid'`` must
        produce a ``rules_L5`` attribution entry with
        negative impact."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = [
            {"action": "raise_10pct", "reason": "r", "profit_score": 0.5, "risk_score": 0.3},
        ]
        context = {
            "total_memories": 0,
            "rules": [{
                "id": "R-99",
                "action": "avoid",
                "condition": "never raise_10pct on low-inventory",
                "confidence": 0.9,
                "rule": "avoid raise_10pct on low-inventory",
            }],
        }
        scored = eng._score_options(
            options, context, {"price": 100, "cost": 40},
            category="pricing",
        )
        entries = [a for a in scored[0]["attribution"] if a["source"] == "rules_L5"]
        assert entries
        assert entries[0]["impact"] < 0

    def test_rules_applied_derived_from_winner_attribution(self, tmp_path):
        """``Decision.rules_applied`` must mirror the winning
        option's attribution rule_ids, not unrelated context
        rules."""
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import Decision
        attribution = [
            {"source": "memory_best_case", "rule_id": "best_case:x",
             "description": "worked", "impact": 0.1},
            {"source": "rules_L5", "rule_id": "R-7",
             "description": "prefer", "impact": 0.08},
        ]
        d = Decision(
            choice="x", reason="r", score=0.7,
            category="pricing", attribution=attribution,
        )
        assert d.rules_applied == ["best_case:x", "R-7"]


class TestDecisionEngineAttributionEntryShape:
    """Every attribution entry must follow the standard
    schema so downstream consumers (dashboards, audit logs)
    can depend on the shape."""

    def test_every_entry_has_required_fields(self, tmp_path):
        from core.learning.action_weights import (
            get_action_weight_store, reset_action_weight_store,
        )
        reset_action_weight_store(tmp_path / "w.db")
        store = get_action_weight_store()
        for _ in range(10):
            store.record("pricing", "raise_10pct", 5.0)

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        dec = eng.decide("pricing", {"price": 100, "cost": 30})
        for entry in dec.attribution:
            assert set(entry.keys()) >= {
                "source", "rule_id", "description", "impact",
            }, f"entry missing keys: {entry}"
            assert isinstance(entry["source"], str)
            assert isinstance(entry["rule_id"], str)
            assert isinstance(entry["description"], str)
            assert isinstance(entry["impact"], (int, float))


class TestDecisionBrainAttribution:
    """``DecisionBrain._decide`` must attach attribution to
    every decision dict it emits, explaining the priority
    source + goal weight contribution."""

    def test_brain_decisions_carry_attribution(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [{
                "id": "p1", "name": "Widget",
                "price": 50.0, "cost": 20.0,
                "inventory_quantity": 10, "image_url": "x",
            }],
            "orders": [],
            "customers": [],
        })
        # There may or may not be decisions depending on
        # diagnosis, but if there are, each one must have
        # attribution.
        for dec in thought.get("decisions", []):
            assert "attribution" in dec, (
                f"brain decision missing attribution: {dec}"
            )
            assert isinstance(dec["attribution"], list)

    def test_brain_attribution_carries_priority_source(self):
        """Any decision that came from a critical/high
        problem must carry a ``priority_rule`` attribution
        entry."""
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        # Zero inventory → triggers a critical problem
        thought = brain.think({
            "products": [{
                "id": "p1", "name": "Widget",
                "price": 50.0, "cost": 20.0,
                "inventory_quantity": 0, "image_url": "x",
            }],
            "orders": [],
            "customers": [],
        })
        decisions = thought.get("decisions", [])
        # At least one decision should have a priority_rule
        # attribution entry
        found = False
        for dec in decisions:
            for a in dec.get("attribution", []):
                if a.get("source") == "priority_rule":
                    found = True
                    break
        assert found or not decisions, (
            "at least one brain decision should have a "
            "priority_rule attribution entry"
        )

    def test_brain_attribution_carries_goal_weight_when_nonneutral(self):
        """When a goal boosts a decision's score (goal weight
        != 1.0), the attribution must carry a ``goal_weight``
        entry."""
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think(
            {
                "products": [{
                    "id": "p1", "name": "Widget",
                    "price": 50.0, "cost": 20.0,
                    "inventory_quantity": 0, "image_url": "x",
                }],
                "orders": [],
                "customers": [],
            },
            goal="survive_crisis",
        )
        decisions = thought.get("decisions", [])
        found_goal = False
        for dec in decisions:
            for a in dec.get("attribution", []):
                if a.get("source") == "goal_weight":
                    found_goal = True
                    # rule_id must encode goal:type pair
                    assert dec.get("goal", "") == "survive_crisis"
                    assert a["rule_id"].startswith("goal:survive_crisis:")
        # Not all decisions will have goal_weight — only ones
        # whose action has a non-1.0 weight in the goal table.
        # So this is a soft check: we want at least one when
        # the goal is set AND there are decisions.
        if decisions:
            assert found_goal or all(
                float(d.get("goal_weight", 1.0)) == 1.0 for d in decisions
            ), (
                "at least one decision with a non-1.0 goal "
                "weight should have a goal_weight attribution"
            )


class TestAttributionSurfacesInThoughtOutput:
    """The full ``brain.think()`` output must expose
    attribution all the way through — operators should be
    able to pull a decision's attribution from
    ``thought["decisions"][i]["attribution"]`` without any
    post-processing."""

    def test_end_to_end_attribution_visible(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [{
                "id": "p1", "name": "Widget",
                "price": 50.0, "cost": 20.0,
                "inventory_quantity": 0, "image_url": "x",
            }],
            "orders": [],
            "customers": [],
        }, goal="survive_crisis")
        # Walk the decisions and assert attribution is a list
        # of dicts with the required keys on every entry.
        for dec in thought.get("decisions", []):
            attribution = dec.get("attribution", [])
            assert isinstance(attribution, list)
            for entry in attribution:
                assert set(entry.keys()) >= {
                    "source", "rule_id", "description", "impact",
                }
