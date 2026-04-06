"""Tests for the Curiosity drive."""
import tempfile

import pytest


def _real_self_model():
    from core.cognitive.self_model import SelfModel
    return SelfModel(db_path=tempfile.mktemp(suffix=".db"))


def _real_goal_manager():
    from core.cognitive.goals import GoalManager
    return GoalManager(db_path=tempfile.mktemp(suffix=".db"))


def _curio(**kwargs):
    from core.cognitive.curiosity import Curiosity
    # Force a deterministic RNG so test rolls are reproducible
    kwargs.setdefault("rng_seed", 42)
    return Curiosity(**kwargs)


# ── Dataclasses ───────────────────────────────────────────────


class TestDataclasses:
    def test_candidate_to_dict(self):
        from core.cognitive.curiosity import CuriosityCandidate
        c = CuriosityCandidate(
            name="x", novelty=0.8, uncertainty=0.6,
            relevance=0.4, recency=0.2, score=0.55,
            evidence_count=3, confidence=0.4,
        )
        d = c.to_dict()
        assert d["name"] == "x"
        assert d["score"] == 0.55
        assert d["evidence_count"] == 3

    def test_recommendation_to_dict(self):
        from core.cognitive.curiosity import (
            CuriosityRecommendation, CuriosityCandidate,
        )
        r = CuriosityRecommendation(
            action_kind="explore",
            target="x",
            reason="why",
            epsilon_used=0.25,
            candidates=[CuriosityCandidate(name="x")],
        )
        d = r.to_dict()
        assert d["action_kind"] == "explore"
        assert d["target"] == "x"
        assert len(d["candidates"]) == 1


# ── candidates() ──────────────────────────────────────────────


class TestCandidates:
    def test_no_self_model_returns_empty(self):
        c = _curio()
        assert c.candidates() == []

    def test_no_capabilities_returns_empty(self):
        sm = _real_self_model()
        c = _curio(self_model=sm)
        assert c.candidates() == []

    def test_unknown_capability_has_high_novelty(self):
        sm = _real_self_model()
        sm.assess("engine.alpha", 0.5, evidence_count=1)
        c = _curio(self_model=sm)
        cands = c.candidates()
        assert len(cands) == 1
        # 1 observation → novelty = 1/(1+1) = 0.5
        assert cands[0].novelty == pytest.approx(0.5)

    def test_well_known_capability_has_low_novelty(self):
        sm = _real_self_model()
        for _ in range(50):
            sm.assess("engine.well_known", 0.8, source="cycle")
        c = _curio(self_model=sm)
        cands = c.candidates()
        assert len(cands) == 1
        assert cands[0].novelty < 0.05

    def test_uncertainty_inverse_of_confidence(self):
        sm = _real_self_model()
        sm.assess("engine.x", 0.5, evidence_count=20)
        c = _curio(self_model=sm)
        cands = c.candidates()
        cap = cands[0]
        # Confidence ~0.96 (tanh(20/10)) → uncertainty ~0.04
        assert cap.uncertainty < 0.1

    def test_ranked_high_to_low(self):
        sm = _real_self_model()
        sm.assess("engine.unknown", 0.5, evidence_count=1)
        sm.assess("engine.known", 0.9, evidence_count=30)
        c = _curio(self_model=sm)
        cands = c.candidates()
        # Unknown should rank higher (more novel + more uncertain)
        assert cands[0].name == "engine.unknown"

    def test_top_n_limit(self):
        sm = _real_self_model()
        for i in range(20):
            sm.assess(f"engine.x{i}", 0.5, evidence_count=1)
        c = _curio(self_model=sm)
        assert len(c.candidates(top_n=5)) == 5

    def test_relevance_from_prefix_popularity(self):
        sm = _real_self_model()
        # Three engine.* and one knowledge.* → engine prefix popularity = 3
        for name in ("engine.a", "engine.b", "engine.c", "knowledge.d"):
            sm.assess(name, 0.5, evidence_count=1)
        c = _curio(self_model=sm)
        cands = {x.name: x for x in c.candidates()}
        # engine.* relevance is 3/3 = 1.0
        assert cands["engine.a"].relevance == 1.0
        # knowledge.* relevance is 1/3 ≈ 0.33
        assert cands["knowledge.d"].relevance == pytest.approx(1 / 3)

    def test_broken_self_model_safe(self):
        class Broken:
            def capabilities(self):
                raise RuntimeError("db down")
        c = _curio(self_model=Broken())
        assert c.candidates() == []


# ── recommend() — explore vs exploit ──────────────────────────


class TestRecommend:
    def test_exploit_when_no_candidates(self):
        sm = _real_self_model()
        c = _curio(self_model=sm)
        rec = c.recommend()
        assert rec.action_kind == "exploit"
        assert rec.target is None

    def test_explore_when_roll_below_epsilon(self):
        sm = _real_self_model()
        sm.assess("engine.unknown", 0.5, evidence_count=1)
        # max_epsilon=1.0 lifts the production ceiling for this test
        # so we can guarantee an explore decision regardless of seed
        c = _curio(self_model=sm, epsilon=0.99, max_epsilon=1.0)
        rec = c.recommend()
        assert rec.action_kind == "explore"
        assert rec.target == "engine.unknown"

    def test_exploit_when_epsilon_floor(self):
        sm = _real_self_model()
        sm.assess("engine.unknown", 0.5, evidence_count=1)
        # Lowest possible epsilon → almost always exploit
        c = _curio(self_model=sm, epsilon=0.0)
        # Try multiple rolls; with our seeded RNG and floor(0.05),
        # most should be exploit
        kinds = [c.recommend().action_kind for _ in range(20)]
        assert kinds.count("exploit") > kinds.count("explore")

    def test_records_epsilon_in_recommendation(self):
        sm = _real_self_model()
        sm.assess("x", 0.5, evidence_count=1)
        c = _curio(self_model=sm, epsilon=0.3)
        rec = c.recommend()
        # Adaptive epsilon may shift but should be in [floor, ceiling]
        assert 0.05 <= rec.epsilon_used <= 0.45

    def test_candidates_included_in_recommendation(self):
        sm = _real_self_model()
        sm.assess("a", 0.5, evidence_count=1)
        sm.assess("b", 0.5, evidence_count=1)
        c = _curio(self_model=sm)
        rec = c.recommend()
        assert len(rec.candidates) == 2


# ── Adaptive epsilon ──────────────────────────────────────────


class TestAdaptiveEpsilon:
    def test_high_confidence_boosts_epsilon(self):
        sm = _real_self_model()
        # Lots of high-confidence capabilities → boost
        for i in range(5):
            sm.assess(f"engine.x{i}", 0.8, evidence_count=30)
        c = _curio(self_model=sm, epsilon=0.20)
        rec = c.recommend()
        # 0.20 base + 0.10 boost = 0.30 (within ceiling)
        assert rec.epsilon_used >= 0.25

    def test_low_confidence_penalizes_epsilon(self):
        sm = _real_self_model()
        for i in range(5):
            sm.assess(f"engine.x{i}", 0.5, evidence_count=1)
        c = _curio(self_model=sm, epsilon=0.20)
        rec = c.recommend()
        # 0.20 base - 0.10 penalty = 0.10 (within floor)
        assert rec.epsilon_used < 0.20

    def test_constructor_clamps_epsilon(self):
        from core.cognitive.curiosity import Curiosity
        # Above ceiling
        c1 = Curiosity(epsilon=0.99)
        assert c1.base_epsilon() <= 0.45
        # Below floor
        c2 = Curiosity(epsilon=-0.5)
        assert c2.base_epsilon() >= 0.05


class TestOutcomeHistory:
    def test_successful_history_boosts_epsilon(self):
        sm = _real_self_model()
        # Mid-confidence SelfModel so neither high-conf boost nor
        # low-conf penalty fires — only the history shift moves the
        # epsilon away from the base.
        for i in range(3):
            sm.assess(f"engine.x{i}", 0.5, evidence_count=10)
        c = _curio(self_model=sm, epsilon=0.20)
        baseline = c.recommend().epsilon_used
        for _ in range(5):
            c.record_exploration_outcome(True)
        rec = c.recommend()
        # Successful history should add ~0.05
        assert rec.epsilon_used > baseline

    def test_failed_history_lowers_epsilon(self):
        sm = _real_self_model()
        sm.assess("x", 0.5, evidence_count=1)
        c = _curio(self_model=sm, epsilon=0.30)
        for _ in range(5):
            c.record_exploration_outcome(False)
        rec = c.recommend()
        # Should be lower than the base 0.30
        assert rec.epsilon_used < 0.30

    def test_outcome_history_capped_at_10(self):
        sm = _real_self_model()
        c = _curio(self_model=sm)
        for _ in range(20):
            c.record_exploration_outcome(True)
        # Internal state should not grow unbounded
        assert len(c._exploration_outcomes) == 10


# ── propose_exploration_goal ──────────────────────────────────


class TestProposeExplorationGoal:
    def test_creates_goal_when_explore_recommended(self):
        sm = _real_self_model()
        sm.assess("engine.mystery", 0.5, evidence_count=1)
        gm = _real_goal_manager()
        c = _curio(
            self_model=sm, goal_manager=gm,
            epsilon=0.99, max_epsilon=1.0,
        )
        gid = c.propose_exploration_goal()
        assert gid is not None
        g = gm.get(gid)
        assert "engine.mystery" in g["what"]
        assert g["source"].startswith("curiosity:")

    def test_no_goal_when_exploit_recommended(self):
        sm = _real_self_model()
        sm.assess("engine.x", 0.5, evidence_count=1)
        gm = _real_goal_manager()
        c = _curio(self_model=sm, goal_manager=gm, epsilon=0.0)
        gid = c.propose_exploration_goal()
        assert gid is None
        # No goals were created
        assert gm.list_goals() == []

    def test_no_goal_when_no_candidates(self):
        gm = _real_goal_manager()
        c = _curio(self_model=_real_self_model(), goal_manager=gm)
        assert c.propose_exploration_goal() is None

    def test_no_goal_manager_returns_none(self):
        sm = _real_self_model()
        sm.assess("x", 0.5, evidence_count=1)
        c = _curio(self_model=sm, epsilon=0.99)
        assert c.propose_exploration_goal() is None


# ── End-to-end ────────────────────────────────────────────────


class TestEndToEnd:
    def test_curiosity_drives_goal_pipeline(self):
        """SelfModel gap → Curiosity recommendation → GoalManager goal."""
        sm = _real_self_model()
        gm = _real_goal_manager()

        # Seed: one well-known, one unknown
        sm.assess("engine.known", 0.85, evidence_count=30)
        sm.assess("engine.mystery", 0.5, evidence_count=1)

        c = _curio(
            self_model=sm, goal_manager=gm,
            epsilon=0.99, max_epsilon=1.0,
        )
        rec = c.recommend()
        assert rec.action_kind == "explore"
        # Top candidate should be the unknown one (more novel + more uncertain)
        assert rec.target == "engine.mystery"

        # The goal pipeline picks it up
        gid = c.propose_exploration_goal()
        assert gid is not None
        g = gm.get(gid)
        assert "engine.mystery" in g["what"]


class TestSingleton:
    def test_get_curiosity_cached(self):
        from core.cognitive import curiosity as mod
        mod._instance = None
        a = mod.get_curiosity()
        b = mod.get_curiosity()
        assert a is b
