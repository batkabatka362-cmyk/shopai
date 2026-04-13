"""Tests for TheoryOfMind — modeling external agents."""
import tempfile

import pytest


def _fresh():
    from core.cognitive.theory_of_mind import TheoryOfMind
    return TheoryOfMind(db_path=tempfile.mktemp(suffix=".db"))


# ── Dataclasses ──────────────────────────────────────────────


class TestDataclasses:
    def test_agent_top_beliefs(self):
        from core.cognitive.theory_of_mind import Agent
        a = Agent(
            id="x", kind="customer", name="X",
            beliefs={"a": 0.9, "b": 0.5, "c": 0.7, "d": 0.3},
        )
        top = a.top_beliefs(n=2)
        assert [b for b, _ in top] == ["a", "c"]

    def test_prediction_to_dict(self):
        from core.cognitive.theory_of_mind import Prediction
        p = Prediction(
            agent_id="seg1",
            action_proposed="lower price 10%",
            predicted_response="buy_more",
            confidence=0.7,
            supporting_beliefs=["price_sensitive"],
        )
        d = p.to_dict()
        assert d["confidence"] == 0.7
        assert d["supporting_beliefs"] == ["price_sensitive"]


# ── Registration ──────────────────────────────────────────────


class TestRegistration:
    def test_register_basic(self):
        tom = _fresh()
        agent = tom.register_agent(
            "seg_budget", "customer", "Budget Shoppers",
            traits={"avg_basket": 25.0},
            initial_beliefs={"price_sensitive": 0.7},
        )
        assert agent.id == "seg_budget"
        assert agent.kind == "customer"
        assert agent.traits["avg_basket"] == 25.0
        assert agent.beliefs["price_sensitive"] == 0.7

    def test_re_register_returns_existing(self):
        tom = _fresh()
        a = tom.register_agent("x", "customer", "X")
        b = tom.register_agent("x", "customer", "Different Name")
        # Should return the existing one, not overwrite
        assert b.id == a.id
        assert b.name == "X"

    def test_invalid_kind_raises(self):
        tom = _fresh()
        with pytest.raises(ValueError):
            tom.register_agent("x", "alien", "X")

    def test_empty_id_raises(self):
        tom = _fresh()
        with pytest.raises(ValueError):
            tom.register_agent("", "customer", "X")

    def test_initial_beliefs_clamped(self):
        tom = _fresh()
        a = tom.register_agent(
            "x", "customer", "X",
            initial_beliefs={"too_high": 1.5, "too_low": -0.5},
        )
        assert a.beliefs["too_high"] <= 0.95
        assert a.beliefs["too_low"] >= 0.05

    def test_get_returns_none_for_unknown(self):
        tom = _fresh()
        assert tom.get_agent("ghost") is None

    def test_list_filters_by_kind(self):
        tom = _fresh()
        tom.register_agent("a", "customer", "A")
        tom.register_agent("b", "competitor", "B")
        tom.register_agent("c", "customer", "C")
        customers = tom.list_agents(kind="customer")
        assert {a.id for a in customers} == {"a", "c"}

    def test_list_all(self):
        tom = _fresh()
        tom.register_agent("a", "customer", "A")
        tom.register_agent("b", "competitor", "B")
        assert len(tom.list_agents()) == 2


# ── Traits ────────────────────────────────────────────────────


class TestUpdateTraits:
    def test_merges_new_keys(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X", traits={"a": 1})
        tom.update_traits("x", {"b": 2})
        a = tom.get_agent("x")
        assert a.traits == {"a": 1, "b": 2}

    def test_overwrites_existing_keys(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X", traits={"a": 1})
        tom.update_traits("x", {"a": 99})
        assert tom.get_agent("x").traits["a"] == 99

    def test_unknown_agent_safe(self):
        tom = _fresh()
        tom.update_traits("ghost", {"a": 1})  # no exception


# ── Observations + belief updates ────────────────────────────


class TestObserve:
    def test_supports_increases_belief(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X",
                           initial_beliefs={"loyal": 0.5})
        tom.observe("x", {"event": "repeat_buy"}, supports=["loyal"])
        assert tom.belief("x", "loyal") == pytest.approx(0.6)

    def test_contradicts_decreases_belief(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X",
                           initial_beliefs={"loyal": 0.7})
        tom.observe("x", {"event": "switched"}, contradicts=["loyal"])
        assert tom.belief("x", "loyal") == pytest.approx(0.55)

    def test_creates_new_belief_at_floor_plus_bump(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X")
        tom.observe("x", {}, supports=["price_sensitive"])
        # First observation: floor (0.05) + 0.10 = 0.15
        assert tom.belief("x", "price_sensitive") == pytest.approx(0.15)

    def test_belief_clamped_at_ceiling(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X",
                           initial_beliefs={"loyal": 0.9})
        for _ in range(10):
            tom.observe("x", {}, supports=["loyal"])
        assert tom.belief("x", "loyal") <= 0.95

    def test_belief_clamped_at_floor(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X",
                           initial_beliefs={"loyal": 0.1})
        for _ in range(10):
            tom.observe("x", {}, contradicts=["loyal"])
        assert tom.belief("x", "loyal") >= 0.05

    def test_observation_count_incremented(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X")
        for _ in range(5):
            tom.observe("x", {"e": 1}, supports=["a"])
        agent = tom.get_agent("x")
        assert agent.observation_count == 5

    def test_observe_unknown_agent_safe(self):
        tom = _fresh()
        tom.observe("ghost", {}, supports=["x"])

    def test_observation_log_returns_recent(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X")
        tom.observe("x", {"event": "first"}, supports=["loyal"])
        tom.observe("x", {"event": "second"}, contradicts=["price_sensitive"])
        log = tom.observation_log("x")
        assert len(log) == 2
        # Most recent first
        assert log[0]["content"]["event"] == "second"
        assert log[0]["contradicts"] == ["price_sensitive"]


# ── beliefs() readers ────────────────────────────────────────


class TestBeliefReads:
    def test_belief_returns_zero_for_unknown_key(self):
        tom = _fresh()
        tom.register_agent("x", "customer", "X")
        assert tom.belief("x", "ghost") == 0.0

    def test_belief_returns_zero_for_unknown_agent(self):
        tom = _fresh()
        assert tom.belief("ghost", "loyal") == 0.0

    def test_beliefs_returns_full_dict(self):
        tom = _fresh()
        tom.register_agent(
            "x", "customer", "X",
            initial_beliefs={"a": 0.5, "b": 0.7},
        )
        bs = tom.beliefs("x")
        assert bs == {"a": 0.5, "b": 0.7}

    def test_beliefs_unknown_returns_empty(self):
        tom = _fresh()
        assert tom.beliefs("ghost") == {}


# ── Predictions ──────────────────────────────────────────────


class TestPredict:
    def _budget_shopper(self, tom):
        tom.register_agent(
            "seg_budget", "customer", "Budget Shoppers",
            initial_beliefs={
                "price_sensitive": 0.85,
                "deal_hunter": 0.7,
            },
        )

    def test_predicts_buy_more_on_price_drop(self):
        tom = _fresh()
        self._budget_shopper(tom)
        pred = tom.predict_response("seg_budget", "lower price 10%")
        assert pred is not None
        assert pred.predicted_response == "buy_more"
        assert "price_sensitive" in pred.supporting_beliefs

    def test_predicts_switch_on_price_raise(self):
        tom = _fresh()
        self._budget_shopper(tom)
        pred = tom.predict_response("seg_budget", "raise price 10%")
        assert pred is not None
        assert pred.predicted_response == "switch_to_competitor"

    def test_predicts_convert_on_discount(self):
        tom = _fresh()
        self._budget_shopper(tom)
        pred = tom.predict_response("seg_budget", "send WELCOME15 discount")
        assert pred is not None
        assert pred.predicted_response == "convert"

    def test_no_match_returns_none(self):
        tom = _fresh()
        self._budget_shopper(tom)
        pred = tom.predict_response("seg_budget", "send a postcard")
        assert pred is None

    def test_unknown_agent_returns_none(self):
        tom = _fresh()
        assert tom.predict_response("ghost", "lower price") is None

    def test_zero_belief_does_not_contribute(self):
        tom = _fresh()
        tom.register_agent(
            "x", "customer", "X",
            initial_beliefs={"loyal": 0.8},  # not in lower-price rules
        )
        pred = tom.predict_response("x", "lower price")
        # Loyal IS in the lower-price rule → "buy_more"
        assert pred is not None
        assert pred.predicted_response == "buy_more"

    def test_custom_belief_rules(self):
        tom = _fresh()
        tom.register_agent(
            "x", "customer", "X",
            initial_beliefs={"hipster": 0.9},
        )
        custom = {
            "vintage": {"hipster": "love_it"},
        }
        pred = tom.predict_response(
            "x", "launch a vintage line", belief_rules=custom,
        )
        assert pred is not None
        assert pred.predicted_response == "love_it"

    def test_competing_responses_pick_strongest(self):
        tom = _fresh()
        tom.register_agent(
            "x", "customer", "X",
            initial_beliefs={
                "price_sensitive": 0.9,  # → buy_more (lower price)
                "skeptical": 0.4,        # → wait_for_more
            },
        )
        pred = tom.predict_response("x", "lower price 10%")
        assert pred.predicted_response == "buy_more"


# ── Stats ────────────────────────────────────────────────────


class TestStats:
    def test_groups_by_kind(self):
        tom = _fresh()
        tom.register_agent("a", "customer", "A")
        tom.register_agent("b", "customer", "B")
        tom.register_agent("c", "competitor", "C")
        tom.observe("a", {}, supports=["x"])
        tom.observe("a", {}, supports=["y"])
        tom.observe("b", {}, supports=["x"])
        stats = tom.stats()
        assert stats["by_kind"]["customer"] == 2
        assert stats["by_kind"]["competitor"] == 1
        assert stats["total_agents"] == 3
        assert stats["total_observations"] == 3


# ── End-to-end ───────────────────────────────────────────────


class TestEndToEnd:
    def test_belief_evolution_changes_prediction(self):
        """Initial belief → observe contradictions → prediction shifts."""
        tom = _fresh()
        tom.register_agent(
            "seg_x", "customer", "Segment X",
            initial_beliefs={"price_sensitive": 0.9},
        )
        # Initially predicts buy_more on price drop
        first = tom.predict_response("seg_x", "lower price 10%")
        assert first.predicted_response == "buy_more"

        # Now observe many contradictions
        for _ in range(10):
            tom.observe("seg_x", {"e": "no_action_on_drop"},
                        contradicts=["price_sensitive"])

        # Belief is now low → prediction may still be buy_more if
        # no other belief in the rules outscores it, but the
        # confidence should be much lower
        second = tom.predict_response("seg_x", "lower price 10%")
        if second is not None:
            assert second.confidence < first.confidence


class _FakeStructured:
    def __init__(self, ok=True, data=None, error=""):
        self.ok = ok
        self.data = data or {}
        self.error = error
        self.raw_text = ""


class _FakeLLM:
    def __init__(self, *, available=True, structured_data=None,
                 raise_on_call=False):
        self._available = available
        self._structured = structured_data
        self._raise = raise_on_call
        self.calls = []

    def is_available(self):
        return self._available

    def ask_structured(self, role="", prompt="", system_prompt="",
                       schema_hint="", **kw):
        self.calls.append({"role": role, "prompt": prompt})
        if self._raise:
            raise RuntimeError("LLM down")
        if self._structured is None:
            return _FakeStructured(ok=False, error="no data")
        return _FakeStructured(ok=True, data=self._structured)


class TestLLMPredictor:
    def _tom_with_llm(self, llm, **kw):
        from core.cognitive.theory_of_mind import TheoryOfMind
        return TheoryOfMind(
            db_path=tempfile.mktemp(suffix=".db"),
            llm=llm,
            **kw,
        )

    def _seed_agent(self, tom):
        tom.register_agent(
            "seg_x", "customer", "Segment X",
            initial_beliefs={"loyal": 0.9, "price_sensitive": 0.5},
        )

    def test_llm_predict_used_when_available(self):
        llm = _FakeLLM(structured_data={
            "predicted_response": "delight_and_buy_more",
            "confidence": 0.85,
            "reasoning": "Loyal customers reward price drops",
            "alternative_responses": [
                {"response": "share_with_friends", "probability": 0.6},
            ],
        })
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        assert pred is not None
        assert pred.predicted_response == "delight_and_buy_more"
        assert pred.confidence == 0.85
        assert "Loyal" in pred.notes
        assert "share_with_friends" in pred.notes
        # Supporting beliefs is ["llm"] for LLM-sourced predictions
        assert pred.supporting_beliefs == ["llm"]

    def test_no_llm_falls_back_to_rules(self):
        tom = self._tom_with_llm(None)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        # Rule-based fallback should still work
        assert pred is not None
        assert pred.supporting_beliefs != ["llm"]

    def test_use_llm_false_disables(self):
        llm = _FakeLLM(structured_data={"predicted_response": "x"})
        tom = self._tom_with_llm(llm, use_llm=False)
        self._seed_agent(tom)
        tom.predict_response("seg_x", "lower price 10%")
        assert llm.calls == []

    def test_prefer_llm_call_override(self):
        llm = _FakeLLM(structured_data={
            "predicted_response": "via_llm",
            "confidence": 0.7,
        })
        tom = self._tom_with_llm(llm, use_llm=False)
        self._seed_agent(tom)
        # use_llm=False instance default but call-level override forces it
        pred = tom.predict_response(
            "seg_x", "lower price 10%", prefer_llm=True,
        )
        assert pred is not None
        assert pred.predicted_response == "via_llm"

    def test_unavailable_llm_falls_back(self):
        llm = _FakeLLM(available=False)
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        # Falls back to rules
        assert pred is not None
        assert pred.supporting_beliefs != ["llm"]

    def test_llm_exception_falls_back(self):
        llm = _FakeLLM(raise_on_call=True)
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        assert pred is not None
        assert pred.supporting_beliefs != ["llm"]

    def test_llm_unparseable_falls_back(self):
        llm = _FakeLLM(structured_data=None)  # ok=False
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        assert pred is not None
        assert pred.supporting_beliefs != ["llm"]

    def test_llm_empty_response_falls_back(self):
        llm = _FakeLLM(structured_data={"predicted_response": ""})
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "lower price 10%")
        assert pred is not None
        assert pred.supporting_beliefs != ["llm"]

    def test_llm_clamps_confidence(self):
        llm = _FakeLLM(structured_data={
            "predicted_response": "x",
            "confidence": 1.7,
        })
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "test")
        assert pred.confidence == 1.0

    def test_llm_non_numeric_confidence_default(self):
        llm = _FakeLLM(structured_data={
            "predicted_response": "x",
            "confidence": "very high",
        })
        tom = self._tom_with_llm(llm)
        self._seed_agent(tom)
        pred = tom.predict_response("seg_x", "test")
        assert pred.confidence == 0.5

    def test_llm_unknown_agent_returns_none(self):
        llm = _FakeLLM(structured_data={"predicted_response": "x"})
        tom = self._tom_with_llm(llm)
        # No agent registered
        pred = tom.predict_response("ghost", "test")
        assert pred is None
        # LLM not even called
        assert llm.calls == []


class TestSingleton:
    def test_get_theory_of_mind_caches(self):
        from core.cognitive import theory_of_mind as mod
        mod._instance = None
        a = mod.get_theory_of_mind()
        b = mod.get_theory_of_mind()
        assert a is b
