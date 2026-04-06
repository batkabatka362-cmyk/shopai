"""Tests for the Reflection module (meta-cognition).

Covers statistical analyses (trends, extremes, patterns, blind spots),
goal revision as a side effect, and integration with real SelfModel +
GoalManager + MemoryIntelligence instances.
"""
import tempfile
import time

import pytest


# ── Helpers ───────────────────────────────────────────────────

class FakeMemory:
    """Minimal MemoryIntelligence-compatible fake.

    Stores episodes internally and responds to retrieve(category=...).
    Episode shape matches what the real MemoryIntelligence would return.
    """

    def __init__(self, episodes=None):
        # Map category → list of episodes
        self._by_cat: dict[str, list[dict]] = {}
        for ep in (episodes or []):
            cat = ep.get("category", "action")
            self._by_cat.setdefault(cat, []).append(ep)

    def add(self, category, action="", score=3.0, timestamp=None, **extra):
        ep = {
            "category": category,
            "action": action,
            "score": score,
            "timestamp": timestamp or time.time(),
            **extra,
        }
        self._by_cat.setdefault(category, []).append(ep)
        return ep

    def retrieve(self, category="", limit=100, **kwargs):
        if category:
            return list(self._by_cat.get(category, []))[-limit:]
        all_eps = []
        for eps in self._by_cat.values():
            all_eps.extend(eps)
        return all_eps[-limit:]


def _reflection(**overrides):
    from core.cognitive.reflection import Reflection
    return Reflection(**overrides)


def _real_self_model():
    from core.cognitive.self_model import SelfModel
    return SelfModel(db_path=tempfile.mktemp(suffix=".db"))


def _real_goal_manager():
    from core.cognitive.goals import GoalManager
    return GoalManager(db_path=tempfile.mktemp(suffix=".db"))


# ── Basic structure ───────────────────────────────────────────

class TestLesson:
    def test_to_dict_shape(self):
        from core.cognitive.reflection import Lesson
        l = Lesson(
            type="strength", subject="x", evidence="always works",
            confidence=0.9, score_after=0.95,
            recommended_action="keep it",
        )
        d = l.to_dict()
        assert d["type"] == "strength"
        assert d["subject"] == "x"
        assert d["confidence"] == 0.9
        assert d["score_after"] == 0.95


class TestEmptyOrNoData:
    def test_no_memory_returns_empty_report(self):
        r = _reflection()
        report = r.reflect()
        assert report.episodes_reviewed == 0
        assert report.lessons == []
        assert "no episodes" in report.narrative.lower()

    def test_empty_memory_returns_empty_report(self):
        r = _reflection(memory=FakeMemory())
        report = r.reflect()
        assert report.episodes_reviewed == 0
        assert report.lessons == []


# ── Trend detection ───────────────────────────────────────────

class TestDetectTrends:
    def test_improvement_detected(self):
        mem = FakeMemory()
        now = time.time()
        # 5 early bad + 5 late good
        for i in range(5):
            mem.add("action", action="pricing", score=1.5, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="pricing", score=4.5, timestamp=now - 50 + i)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        types = [l.type for l in report.lessons]
        assert "improvement" in types

    def test_regression_detected(self):
        mem = FakeMemory()
        now = time.time()
        for i in range(5):
            mem.add("action", action="marketing", score=4.5, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="marketing", score=1.5, timestamp=now - 50 + i)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert any(l.type == "regression" and l.subject == "marketing" for l in report.lessons)

    def test_no_trend_when_too_few_episodes(self):
        mem = FakeMemory()
        # Only 4 episodes total — below _MIN_EPISODES_FOR_TREND=5
        for i in range(2):
            mem.add("action", action="sparse", score=1.0)
            mem.add("action", action="sparse", score=5.0)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(l.type in ("improvement", "regression") for l in report.lessons)

    def test_small_delta_not_a_trend(self):
        mem = FakeMemory()
        now = time.time()
        for i in range(5):
            mem.add("action", action="stable", score=3.0, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="stable", score=3.1, timestamp=now - 50 + i)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(
            l.type in ("improvement", "regression") and l.subject == "stable"
            for l in report.lessons
        )

    def test_score_normalization_from_1_5_scale(self):
        mem = FakeMemory()
        now = time.time()
        # score=1 (raw) → 0.0 normalized
        # score=5 (raw) → 1.0 normalized
        for i in range(5):
            mem.add("action", action="norm", score=1.0, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="norm", score=5.0, timestamp=now - 50 + i)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        lesson = next(l for l in report.lessons
                      if l.type == "improvement" and l.subject == "norm")
        assert lesson.score_before == 0.0
        assert lesson.score_after == 1.0


# ── Consistent extremes ───────────────────────────────────────

class TestDetectExtremes:
    def test_consistent_strength_detected(self):
        mem = FakeMemory()
        for i in range(10):
            mem.add("action", action="reliable", score=4.5)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert any(
            l.type == "strength" and l.subject == "reliable"
            for l in report.lessons
        )

    def test_consistent_weakness_detected(self):
        mem = FakeMemory()
        for i in range(10):
            mem.add("action", action="terrible", score=1.2)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert any(
            l.type == "weakness" and l.subject == "terrible"
            for l in report.lessons
        )

    def test_noisy_not_classified_as_extreme(self):
        mem = FakeMemory()
        # Alternating high/low → high variance → shouldn't call it strength
        for i in range(10):
            mem.add("action", action="noisy", score=5.0 if i % 2 == 0 else 1.0)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(
            l.type in ("strength", "weakness") and l.subject == "noisy"
            for l in report.lessons
        )


# ── Pattern detection ─────────────────────────────────────────

class TestDetectPatterns:
    def test_positive_pattern_detected(self):
        mem = FakeMemory()
        # A reliably leads to positive outcomes
        for _ in range(6):
            mem.add("action", action="raise_price", score=4.5)
        mem.add("action", action="raise_price", score=1.0)  # one failure
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        pat = next(
            (l for l in report.lessons
             if l.type == "pattern" and l.subject == "raise_price"),
            None,
        )
        assert pat is not None
        assert "prefer" in pat.recommended_action

    def test_negative_pattern_detected(self):
        mem = FakeMemory()
        for _ in range(5):
            mem.add("action", action="dumb_discount", score=1.2)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        pat = next(
            (l for l in report.lessons
             if l.type == "pattern" and l.subject == "dumb_discount"),
            None,
        )
        assert pat is not None
        assert "avoid" in pat.recommended_action

    def test_unknown_action_skipped(self):
        mem = FakeMemory()
        for _ in range(10):
            mem.add("action", action="", score=4.5)  # no action name
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(l.type == "pattern" for l in report.lessons)

    def test_mixed_outcomes_not_a_pattern(self):
        mem = FakeMemory()
        # 3 positive + 3 negative → ratio=0.5 < 0.7 threshold
        for _ in range(3):
            mem.add("action", action="mixed", score=4.5)
        for _ in range(3):
            mem.add("action", action="mixed", score=1.5)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(
            l.type == "pattern" and l.subject == "mixed"
            for l in report.lessons
        )


# ── Blind spots ───────────────────────────────────────────────

class TestBlindSpots:
    def test_blind_spots_from_self_model(self):
        mem = FakeMemory()
        mem.add("action", action="x", score=3.0)  # need at least 1 episode
        sm = _real_self_model()
        # One well-known cap + one barely-seen cap
        sm.assess("engine.known", 0.8, evidence_count=20)
        sm.assess("engine.mystery", 0.5, evidence_count=1)
        r = _reflection(memory=mem, self_model=sm)
        report = r.reflect(apply=False)
        bs = [l for l in report.lessons if l.type == "blind_spot"]
        assert any(l.subject == "engine.mystery" for l in bs)

    def test_no_self_model_no_blind_spots(self):
        mem = FakeMemory()
        mem.add("action", action="x", score=3.0)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert not any(l.type == "blind_spot" for l in report.lessons)


# ── Side effects: SelfModel updates ───────────────────────────

class TestAppliesToSelfModel:
    def test_applies_updates_when_apply_true(self):
        mem = FakeMemory()
        for _ in range(10):
            mem.add("action", action="reliable", score=4.5)
        sm = _real_self_model()
        r = _reflection(memory=mem, self_model=sm)
        report = r.reflect(apply=True)
        assert report.self_model_updates > 0
        # A reflection.reliable capability should now exist
        cap = sm.get_capability("reflection.reliable")
        assert cap is not None
        assert cap["score"] > 0.7

    def test_no_updates_when_apply_false(self):
        mem = FakeMemory()
        for _ in range(10):
            mem.add("action", action="reliable", score=4.5)
        sm = _real_self_model()
        r = _reflection(memory=mem, self_model=sm)
        report = r.reflect(apply=False)
        assert report.self_model_updates == 0
        assert sm.get_capability("reflection.reliable") is None


# ── Side effects: Goal revision ───────────────────────────────

class TestRevisesGoals:
    def test_regression_raises_urgency_of_matching_goal(self):
        mem = FakeMemory()
        now = time.time()
        # regression on engine.broken
        for i in range(5):
            mem.add("action", action="engine.broken", score=4.5, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="engine.broken", score=1.0, timestamp=now - 50 + i)

        gm = _real_goal_manager()
        gid = gm.propose(
            "Fix engine.broken",
            source="self_model.weakness:engine.broken",
            urgency=0.2,
        )

        r = _reflection(memory=mem, goal_manager=gm)
        report = r.reflect(apply=True)
        assert report.goal_revisions >= 1
        revised = gm.get(gid)
        assert revised["urgency"] > 0.2

    def test_improvement_lowers_urgency_of_matching_goal(self):
        mem = FakeMemory()
        now = time.time()
        for i in range(5):
            mem.add("action", action="engine.hopeful", score=1.0, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="engine.hopeful", score=4.5, timestamp=now - 50 + i)

        gm = _real_goal_manager()
        gid = gm.propose(
            "Practice engine.hopeful",
            source="self_model.weakness:engine.hopeful",
            urgency=0.8,
        )
        r = _reflection(memory=mem, goal_manager=gm)
        report = r.reflect(apply=True)
        assert report.goal_revisions >= 1
        revised = gm.get(gid)
        assert revised["urgency"] < 0.8

    def test_no_goal_manager_means_zero_revisions(self):
        mem = FakeMemory()
        now = time.time()
        for i in range(5):
            mem.add("action", action="x", score=1.0, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="x", score=4.5, timestamp=now - 50 + i)
        r = _reflection(memory=mem)
        report = r.reflect(apply=True)
        assert report.goal_revisions == 0

    def test_unrelated_goals_not_revised(self):
        mem = FakeMemory()
        now = time.time()
        for i in range(5):
            mem.add("action", action="subject.a", score=4.5, timestamp=now - 100 + i)
        for i in range(5):
            mem.add("action", action="subject.a", score=1.0, timestamp=now - 50 + i)

        gm = _real_goal_manager()
        gid = gm.propose(
            "Unrelated goal",
            source="self_model.weakness:different_subject",
            urgency=0.5,
        )
        r = _reflection(memory=mem, goal_manager=gm)
        r.reflect(apply=True)
        # The unrelated goal should still be at 0.5
        assert gm.get(gid)["urgency"] == pytest.approx(0.5)


# ── Narrative ─────────────────────────────────────────────────

class TestNarrative:
    def test_mentions_lesson_counts(self):
        mem = FakeMemory()
        for _ in range(10):
            mem.add("action", action="reliable", score=4.5)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        assert "lesson" in report.narrative.lower()
        assert "strength" in report.narrative.lower()

    def test_empty_narrative_when_no_lessons(self):
        mem = FakeMemory()
        mem.add("action", action="one", score=3.0)
        r = _reflection(memory=mem)
        report = r.reflect(apply=False)
        # One episode → no trends, no extremes → no lessons
        assert "no lessons" in report.narrative.lower() or "nothing unusual" in report.narrative.lower()


# ── Episode fetching fallbacks ────────────────────────────────

class TestFetchFallbacks:
    def test_broken_retrieve_returns_empty(self):
        class Broken:
            def retrieve(self, **kw):
                raise RuntimeError("db down")
        r = _reflection(memory=Broken())
        report = r.reflect()
        assert report.episodes_reviewed == 0

    def test_generic_get_all_fallback(self):
        class OldMem:
            def get_all(self, limit=100):
                return [
                    {"action": "x", "score": 4.5, "timestamp": i}
                    for i in range(10)
                ]
        r = _reflection(memory=OldMem())
        report = r.reflect()
        assert report.episodes_reviewed == 10

    def test_category_parameter_narrows_fetch(self):
        mem = FakeMemory()
        for _ in range(5):
            mem.add("action", action="a", score=3.0)
        for _ in range(5):
            mem.add("decision", action="b", score=3.0)
        r = _reflection(memory=mem)
        report = r.reflect(category="decision")
        # Only 5 episodes from the 'decision' category
        assert report.episodes_reviewed == 5


# ── End-to-end ────────────────────────────────────────────────

class TestEndToEnd:
    def test_full_cognitive_loop(self):
        """SelfModel → GoalManager → Reflection → SelfModel updated + goals revised."""
        from core.cognitive.self_model import SelfModel
        from core.cognitive.goals import GoalManager

        sm = SelfModel(db_path=tempfile.mktemp(suffix=".db"))
        gm = GoalManager(db_path=tempfile.mktemp(suffix=".db"))
        mem = FakeMemory()

        # Seed self-model with a known weakness
        for _ in range(15):
            sm.assess("engine.pricing", 0.2, source="cycle")

        # AI generates a goal from the weakness
        ids = gm.propose_from_self_model(sm)
        assert len(ids) >= 1
        pricing_goal_id = next(
            i for i in ids if "engine.pricing" in gm.get(i)["source"]
        )

        # Time passes — memory now shows improvement
        now = time.time()
        for i in range(5):
            mem.add("action", action="engine.pricing", score=1.5, timestamp=now - 200 + i)
        for i in range(5):
            mem.add("action", action="engine.pricing", score=4.5, timestamp=now - 100 + i)

        # Reflect
        r = _reflection(memory=mem, self_model=sm, goal_manager=gm)
        original_urgency = gm.get(pricing_goal_id)["urgency"]
        report = r.reflect(apply=True)

        # Should detect improvement and lower urgency
        assert any(l.type == "improvement" for l in report.lessons)
        assert gm.get(pricing_goal_id)["urgency"] < original_urgency

        # SelfModel should record the reflection.* observation
        assert sm.get_capability("reflection.engine.pricing") is not None


class TestSingleton:
    def test_get_reflection_cached(self):
        from core.cognitive import reflection as mod
        mod._instance = None
        a = mod.get_reflection()
        b = mod.get_reflection()
        assert a is b
