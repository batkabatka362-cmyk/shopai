"""Regression tests for Fix J: experience advice actually
consumed by ``DecisionBrain._decide``.

Pre-fix, ``_consult_experience()`` built a rich dict with
``relevant_strategies`` (per-action effectiveness) and an
``avoid`` list of past mistakes, wrote it to
``thought["experience"]``, and passed it to ``_decide(...)``
— but the ``experience: dict`` parameter was silently
dropped on the floor. Decisions ranked purely on severity +
goal weights. Every cycle rebuilt the advice, every cycle
threw it away.

Core audit re-scan flagged this as the #1 HIGH weakness
(dead data flow from experience to decision ranking). Fix J
makes ``_decide`` actually consume the advice:

  1. When a decision's ``type`` matches an entry in
     ``experience["relevant_strategies"]``, boost the
     score by a multiplier derived from the strategy's
     ``effectiveness`` — successful strategies lift their
     action's score.
  2. When a decision's ``type`` appears in an
     ``experience["avoid"]`` mistake description, dampen
     the score.
  3. Both contributions land in the attribution trail
     under ``source="experience_strategy"`` or
     ``source="experience_mistake"`` so operators can see
     which past outcomes steered the ranking.
"""
from __future__ import annotations

import pytest


class TestExperiencePassedToDecide:
    def test_decide_accepts_experience_dict(self):
        """Baseline contract: ``_decide`` still accepts the
        experience dict parameter and runs without crashing."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [{"id": "p1", "name": "w", "price": 50,
                          "cost": 20, "inventory_quantity": 5,
                          "image_url": "x"}],
            "orders": [], "customers": [],
        })
        # Synthetic experience advice with a strategy for a
        # problem action
        experience = {
            "past_decisions": 3,
            "success_rate": 0.66,
            "relevant_strategies": [
                {"for": "add_images", "strategy": "bulk upload", "effectiveness": 0.9},
            ],
            "avoid": [],
            "recommended_skills": [],
        }
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]
        decisions = brain._decide(state, problems, [], experience)
        assert isinstance(decisions, list)
        assert decisions, "expected at least one decision"


class TestExperienceBoostsMatchingAction:
    """A high-effectiveness strategy entry for a decision's
    action must produce a ``experience_strategy`` attribution
    entry with positive impact, and the final score must
    reflect the boost."""

    def test_strategy_boost_lifts_score(self):
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [{"id": "p1", "name": "w", "price": 50,
                          "cost": 20, "inventory_quantity": 5,
                          "image_url": "x"}],
            "orders": [], "customers": [],
        })
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]

        # Case A: no experience boost
        baseline = brain._decide(state, problems, [], {
            "past_decisions": 0, "relevant_strategies": [], "avoid": [],
        })
        # Case B: strong experience boost for the same action
        boosted = brain._decide(state, problems, [], {
            "past_decisions": 5, "success_rate": 0.9,
            "relevant_strategies": [
                {"for": "add_images", "strategy": "bulk upload",
                 "effectiveness": 0.95},
            ],
            "avoid": [],
        })

        base_score = [d["score"] for d in baseline if d["type"] == "add_images"][0]
        boost_score = [d["score"] for d in boosted if d["type"] == "add_images"][0]
        assert boost_score > base_score, (
            f"experience boost should lift score: "
            f"baseline={base_score}, boosted={boost_score}"
        )

    def test_strategy_boost_attribution_recorded(self):
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [], "orders": [], "customers": [],
        })
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]
        decisions = brain._decide(state, problems, [], {
            "past_decisions": 5,
            "relevant_strategies": [
                {"for": "add_images", "strategy": "bulk upload",
                 "effectiveness": 0.9},
            ],
            "avoid": [],
        })
        d = [x for x in decisions if x["type"] == "add_images"][0]
        sources = [a["source"] for a in d.get("attribution", [])]
        assert "experience_strategy" in sources, (
            f"expected experience_strategy attribution, got {d.get('attribution')}"
        )
        entry = [
            a for a in d["attribution"] if a["source"] == "experience_strategy"
        ][0]
        assert entry["impact"] > 0
        assert entry["rule_id"] == "experience:add_images"

    def test_low_effectiveness_strategy_dampens(self):
        """A strategy entry with low effectiveness should
        DAMPEN the score (effectiveness is a signal in both
        directions)."""
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [], "orders": [], "customers": [],
        })
        problems = [
            {"action": "add_images", "severity": "high",
             "detail": "missing images"},
        ]
        baseline = brain._decide(state, problems, [], {
            "relevant_strategies": [], "avoid": [],
        })
        dampened = brain._decide(state, problems, [], {
            "relevant_strategies": [
                {"for": "add_images", "strategy": "x", "effectiveness": 0.1},
            ],
            "avoid": [],
        })
        base_score = [d["score"] for d in baseline if d["type"] == "add_images"][0]
        damp_score = [d["score"] for d in dampened if d["type"] == "add_images"][0]
        assert damp_score < base_score


class TestExperienceMistakesDampen:
    """Actions mentioned in ``experience["avoid"]`` mistake
    descriptions must produce a negative-impact
    ``experience_mistake`` attribution entry."""

    def test_mistake_hit_dampens_score(self):
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [], "orders": [], "customers": [],
        })
        problems = [
            {"action": "lower_price", "severity": "high",
             "detail": "margin squeeze"},
        ]
        baseline = brain._decide(state, problems, [], {
            "relevant_strategies": [], "avoid": [],
        })
        dampened = brain._decide(state, problems, [], {
            "relevant_strategies": [],
            "avoid": [
                "past attempt to lower_price on low-inventory item lost margin",
            ],
        })
        base_score = [d["score"] for d in baseline if d["type"] == "lower_price"][0]
        damp_score = [d["score"] for d in dampened if d["type"] == "lower_price"][0]
        assert damp_score < base_score

    def test_mistake_attribution_recorded(self):
        from core.brain.decision_brain import DecisionBrain, StoreState
        brain = DecisionBrain()
        brain._init_components()
        state = StoreState({
            "products": [], "orders": [], "customers": [],
        })
        problems = [
            {"action": "lower_price", "severity": "high",
             "detail": "margin squeeze"},
        ]
        decisions = brain._decide(state, problems, [], {
            "avoid": [
                "past attempt to lower_price on low-inventory item lost margin",
            ],
            "relevant_strategies": [],
        })
        d = [x for x in decisions if x["type"] == "lower_price"][0]
        sources = [a["source"] for a in d.get("attribution", [])]
        assert "experience_mistake" in sources
        entry = [a for a in d["attribution"]
                 if a["source"] == "experience_mistake"][0]
        assert entry["impact"] < 0


class TestExperienceEndToEndThroughThink:
    """Full ``brain.think()`` path: experience advice must
    be consulted during ranking and the winning decision
    should carry experience attribution when applicable."""

    def test_think_passes_experience_to_decide(self, monkeypatch):
        """Monkeypatch _decide to capture the experience
        argument, verify think() actually forwards it."""
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        captured = {}
        orig = brain._decide

        def _spy(state, problems, opportunities, experience, *, goal=None):
            captured["experience"] = experience
            return orig(state, problems, opportunities, experience, goal=goal)

        monkeypatch.setattr(brain, "_decide", _spy)
        brain.think({
            "products": [{
                "id": "p1", "name": "w", "price": 50, "cost": 20,
                "inventory_quantity": 5, "image_url": "",
            }],
            "orders": [], "customers": [],
        })
        assert "experience" in captured
        assert isinstance(captured["experience"], dict)
        # Contract: advice dict shape
        assert "relevant_strategies" in captured["experience"]
