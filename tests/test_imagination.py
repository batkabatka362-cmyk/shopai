"""Tests for the cognitive Imagination module."""
import tempfile

import pytest


# ── Helpers ───────────────────────────────────────────────────


class FakeMemory:
    def __init__(self, episodes=None):
        self._by_cat = {}
        for ep in (episodes or []):
            cat = ep.get("category", "action")
            self._by_cat.setdefault(cat, []).append(ep)

    def add(self, category, action="", score=3.0, **extra):
        self._by_cat.setdefault(category, []).append({
            "category": category,
            "action": action,
            "score": score,
            **extra,
        })

    def retrieve(self, category="", limit=100, **kwargs):
        return list(self._by_cat.get(category, []))[-limit:]


def _real_self_model():
    from core.cognitive.self_model import SelfModel
    return SelfModel(db_path=tempfile.mktemp(suffix=".db"))


def _imag(**kwargs):
    from core.cognitive.imagination import Imagination
    return Imagination(**kwargs)


def _step(description, **fields):
    return dict(description=description, **fields)


def _plan(what, steps, backend="heuristic"):
    return {
        "goal_what": what,
        "steps": steps,
        "backend": backend,
    }


# ── Dataclass shapes ──────────────────────────────────────────


class TestDataclasses:
    def test_outcome_to_dict(self):
        from core.cognitive.imagination import ImaginedOutcome
        o = ImaginedOutcome(
            description="x", predicted_score=0.8, predicted_cost=0.2,
            confidence=0.7, sources=["s"], notes="n",
        )
        d = o.to_dict()
        assert d["predicted_score"] == 0.8
        assert d["expected_value"] == pytest.approx(0.8 - 0.5 * 0.2)
        assert d["sources"] == ["s"]

    def test_outcome_expected_value_formula(self):
        from core.cognitive.imagination import ImaginedOutcome
        o = ImaginedOutcome(description="x", predicted_score=1.0, predicted_cost=0.0)
        assert o.expected_value() == 1.0
        o = ImaginedOutcome(description="x", predicted_score=0.0, predicted_cost=1.0)
        assert o.expected_value() == -0.5

    def test_imagined_plan_to_dict(self):
        from core.cognitive.imagination import ImaginedPlan, ImaginedOutcome
        p = ImaginedPlan(plan_what="goal", backend="heuristic")
        p.step_outcomes.append(ImaginedOutcome(description="a"))
        d = p.to_dict()
        assert d["plan_what"] == "goal"
        assert d["step_count"] == 1


# ── Default evaluator: no signals → neutral ───────────────────


class TestNoSignals:
    def test_empty_step_returns_neutral(self):
        outcome = _imag().imagine_step("")
        assert outcome.confidence == 0.0
        assert outcome.predicted_score == 0.5

    def test_step_with_no_evidence_falls_back_to_priors(self):
        outcome = _imag().imagine_step(_step("do something obscure"))
        # No SelfModel, no memory, no step priors → still neutral
        assert outcome.predicted_score == 0.5
        assert outcome.confidence == 0.0


# ── Step prior signal ─────────────────────────────────────────


class TestStepPriors:
    def test_step_with_impact_and_confidence(self):
        step = _step(
            "do thing", estimated_impact=0.9, confidence=0.8, estimated_cost=0.2,
        )
        outcome = _imag().imagine_step(step)
        # Predicted score should be close to the step's estimated impact
        assert outcome.predicted_score > 0.7
        assert outcome.predicted_cost == 0.2
        assert outcome.confidence > 0.0

    def test_explicit_expected_score_takes_priority_over_impact(self):
        step = _step(
            "x", expected_score=0.3, estimated_impact=0.9, confidence=0.5,
        )
        outcome = _imag().imagine_step(step)
        assert outcome.predicted_score < 0.5

    def test_non_numeric_priors_ignored(self):
        step = _step(
            "x", estimated_impact="high", confidence="sure",
        )
        outcome = _imag().imagine_step(step)
        # Falls back to neutral
        assert outcome.predicted_score == 0.5


# ── SelfModel signal ──────────────────────────────────────────


class TestSelfModelSignal:
    def test_known_strength_increases_predicted_score(self):
        sm = _real_self_model()
        sm.assess("engine.pricing", 0.9, evidence_count=20)
        outcome = _imag(self_model=sm).imagine_step(
            _step("Adjust engine.pricing for fashion category"),
        )
        assert outcome.predicted_score > 0.7
        assert any("self_model:engine.pricing" in s for s in outcome.sources)

    def test_known_weakness_decreases_predicted_score(self):
        sm = _real_self_model()
        sm.assess("engine.flaky", 0.1, evidence_count=20)
        outcome = _imag(self_model=sm).imagine_step(
            _step("Run engine.flaky once more"),
        )
        assert outcome.predicted_score < 0.4

    def test_short_name_match_after_prefix_strip(self):
        sm = _real_self_model()
        sm.assess("knowledge.marketing", 0.85, evidence_count=15)
        outcome = _imag(self_model=sm).imagine_step(
            _step("Develop a marketing campaign"),
        )
        assert outcome.predicted_score > 0.6
        assert any("knowledge.marketing" in s for s in outcome.sources)

    def test_no_capability_match_falls_back(self):
        sm = _real_self_model()
        sm.assess("engine.completely_different", 0.9, evidence_count=20)
        outcome = _imag(self_model=sm).imagine_step(
            _step("Do unrelated thing"),
        )
        assert outcome.predicted_score == 0.5
        assert outcome.confidence == 0.0

    def test_broken_self_model_safe(self):
        class Broken:
            def capabilities(self):
                raise RuntimeError("db down")
        outcome = _imag(self_model=Broken()).imagine_step(_step("x"))
        assert outcome.confidence == 0.0


# ── Memory signal ─────────────────────────────────────────────


class TestMemorySignal:
    def test_positive_memory_lifts_score(self):
        mem = FakeMemory()
        for _ in range(8):
            mem.add("action", action="raise_price", score=4.5)
        outcome = _imag(memory=mem).imagine_step(
            _step("Raise price on bestseller"),
        )
        assert outcome.predicted_score > 0.7
        assert any("memory:" in s for s in outcome.sources)

    def test_negative_memory_lowers_score(self):
        mem = FakeMemory()
        for _ in range(8):
            mem.add("action", action="dumb_promo", score=1.2)
        outcome = _imag(memory=mem).imagine_step(
            _step("Try a dumb_promo on cart"),
        )
        assert outcome.predicted_score < 0.3

    def test_no_keyword_match_falls_back(self):
        mem = FakeMemory()
        for _ in range(8):
            mem.add("action", action="something_else", score=4.5)
        outcome = _imag(memory=mem).imagine_step(
            _step("Completely different topic"),
        )
        assert outcome.confidence == 0.0

    def test_normalizes_1_5_scale(self):
        mem = FakeMemory()
        # All score 5.0 → normalized to 1.0
        for _ in range(8):
            mem.add("action", action="reliable_thing", score=5.0)
        outcome = _imag(memory=mem).imagine_step(
            _step("Run reliable_thing now"),
        )
        assert outcome.predicted_score > 0.85

    def test_broken_memory_safe(self):
        class Broken:
            def retrieve(self, **kw):
                raise RuntimeError("db down")
        outcome = _imag(memory=Broken()).imagine_step(_step("x"))
        assert outcome.confidence == 0.0


# ── Combined signals ──────────────────────────────────────────


class TestCombinedSignals:
    def test_self_model_plus_memory_plus_prior(self):
        sm = _real_self_model()
        sm.assess("engine.pricing", 0.9, evidence_count=20)
        mem = FakeMemory()
        for _ in range(5):
            mem.add("action", action="pricing", score=4.5)
        step = _step(
            "Optimize engine.pricing",
            estimated_impact=0.85, confidence=0.7, estimated_cost=0.3,
        )
        outcome = _imag(self_model=sm, memory=mem).imagine_step(step)
        # All three sources should fire
        assert len(outcome.sources) >= 3
        # High predicted score because all three agree
        assert outcome.predicted_score > 0.8
        # Confidence should be higher than any single source alone
        assert outcome.confidence > 0.5

    def test_disagreeing_signals_average_out(self):
        # When SelfModel and Memory disagree, the score should be
        # pulled toward the more confident source. Here SelfModel
        # has 20 observations (high confidence) and memory has only 5
        # (lower confidence) so SelfModel dominates but doesn't fully
        # win.
        sm = _real_self_model()
        sm.assess("engine.x", 0.9, evidence_count=20)
        mem = FakeMemory()
        for _ in range(5):
            mem.add("action", action="engine.x", score=1.5)
        outcome = _imag(self_model=sm, memory=mem).imagine_step(_step("Run engine.x"))
        # Mid-to-high range — pulled down from 0.9 by the bad memory,
        # but still above 0.5 because SelfModel is much more confident
        assert 0.5 < outcome.predicted_score < 0.85


# ── imagine_plan ──────────────────────────────────────────────


class TestImaginePlan:
    def test_aggregates_step_outcomes(self):
        step1 = _step("a", estimated_impact=0.9, confidence=0.8, estimated_cost=0.2)
        step2 = _step("b", estimated_impact=0.7, confidence=0.6, estimated_cost=0.3)
        plan = _plan("goal", [step1, step2])
        result = _imag().imagine_plan(plan)
        assert len(result.step_outcomes) == 2
        # Cost is summed
        assert result.expected_cost == pytest.approx(0.5)
        # Score is weighted by confidence: (0.9*0.8 + 0.7*0.6)/(0.8+0.6)
        expected = (0.9 * 0.8 + 0.7 * 0.6) / (0.8 + 0.6)
        assert result.expected_score == pytest.approx(expected, abs=0.05)

    def test_empty_plan_returns_zero(self):
        plan = _plan("goal", [])
        result = _imag().imagine_plan(plan)
        assert result.step_outcomes == []
        assert result.expected_score == 0.0
        assert result.expected_cost == 0.0

    def test_real_planner_plan_works(self):
        """imagine_plan should accept a real Plan from the Planner."""
        from core.cognitive.planner import Planner, HeuristicPlanBackend
        planner = Planner(backends=[HeuristicPlanBackend()])
        plan = planner.plan("Improve weak X")
        result = _imag().imagine_plan(plan)
        assert len(result.step_outcomes) == plan.step_count()
        assert result.backend == "heuristic"

    def test_plan_what_extracted_from_dataclass(self):
        from core.cognitive.planner import Plan, PlanStep
        p = Plan(
            goal_id="g1", goal_what="my goal", backend="x",
            steps=[PlanStep(description="step")],
        )
        result = _imag().imagine_plan(p)
        assert result.plan_what == "my goal"


# ── compare ──────────────────────────────────────────────────


class TestCompare:
    def test_picks_higher_expected_value(self):
        good = _plan("good plan", [
            _step("a", estimated_impact=0.9, confidence=0.9, estimated_cost=0.1),
        ])
        bad = _plan("bad plan", [
            _step("b", estimated_impact=0.2, confidence=0.9, estimated_cost=0.8),
        ])
        result = _imag().compare([good, bad])
        assert result["best"].plan_what == "good plan"
        assert result["ranked"][0].plan_what == "good plan"
        assert result["ranked"][-1].plan_what == "bad plan"
        assert result["by_value"]["good plan"] > result["by_value"]["bad plan"]

    def test_empty_list_returns_none(self):
        result = _imag().compare([])
        assert result["best"] is None
        assert result["ranked"] == []

    def test_three_plans_ranked(self):
        plans = [
            _plan(f"p{i}", [
                _step(f"s{i}", estimated_impact=imp, confidence=0.8, estimated_cost=0.2)
            ])
            for i, imp in enumerate([0.3, 0.9, 0.6])
        ]
        result = _imag().compare(plans)
        scores = [p.expected_value() for p in result["ranked"]]
        assert scores == sorted(scores, reverse=True)
        assert result["best"].plan_what == "p1"  # imp=0.9


# ── Custom evaluator ──────────────────────────────────────────


class TestCustomEvaluator:
    def test_injected_evaluator_used(self):
        from core.cognitive.imagination import ImaginedOutcome
        calls = []

        def my_eval(step):
            calls.append(step)
            return ImaginedOutcome(
                description="custom", predicted_score=0.99, confidence=0.99,
            )

        outcome = _imag(evaluator=my_eval).imagine_step(_step("anything"))
        assert outcome.predicted_score == 0.99
        assert len(calls) == 1

    def test_evaluator_exception_returns_safe_default(self):
        def boom(step):
            raise RuntimeError("explode")

        outcome = _imag(evaluator=boom).imagine_step(_step("x"))
        assert outcome.confidence == 0.0
        assert "evaluator_error" in outcome.sources


# ── Helpers ──────────────────────────────────────────────────


class TestKeywordExtraction:
    def test_extracts_meaningful_words(self):
        from core.cognitive.imagination import _extract_keywords
        kws = _extract_keywords("Optimize engine.pricing for fashion category")
        assert "optimize" in kws
        assert "engine.pricing" in kws
        assert "fashion" in kws
        # Stopwords filtered
        assert "for" not in kws

    def test_empty_text(self):
        from core.cognitive.imagination import _extract_keywords
        assert _extract_keywords("") == []

    def test_caps_at_8_keywords(self):
        from core.cognitive.imagination import _extract_keywords
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        kws = _extract_keywords(text)
        assert len(kws) <= 8


class TestEndToEnd:
    def test_full_phase2_flow(self):
        """Phase 1 + 2.1 + 2.2: SelfModel → Goals → Plan → Imagine."""
        from core.cognitive.self_model import SelfModel
        from core.cognitive.goals import GoalManager
        from core.cognitive.planner import Planner, HeuristicPlanBackend
        from core.cognitive.imagination import Imagination

        sm = SelfModel(db_path=tempfile.mktemp(suffix=".db"))
        gm = GoalManager(db_path=tempfile.mktemp(suffix=".db"))
        mem = FakeMemory()

        # Seed: pricing engine is reliably good
        sm.assess("engine.pricing", 0.85, evidence_count=20)
        for _ in range(8):
            mem.add("action", action="pricing", score=4.5)

        # Generate a goal
        gm.propose("Improve engine.pricing throughput", urgency=0.5)
        goal = gm.list_goals()[0]

        # Plan it
        planner = Planner(backends=[HeuristicPlanBackend()])
        plan = planner.plan(goal)
        assert plan.step_count() > 0

        # Imagine the plan with all signals
        imag = Imagination(self_model=sm, memory=mem)
        imagined = imag.imagine_plan(plan)
        assert len(imagined.step_outcomes) == plan.step_count()
        # At least one step should benefit from a SelfModel/memory hit
        sources_seen = []
        for o in imagined.step_outcomes:
            sources_seen.extend(o.sources)
        assert any("self_model:" in s or "memory:" in s for s in sources_seen)


class TestSingleton:
    def test_get_imagination_cached(self):
        from core.cognitive import imagination as mod
        mod._instance = None
        a = mod.get_imagination()
        b = mod.get_imagination()
        assert a is b
