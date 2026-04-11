"""Tests for Mind — the unified cognitive loop.

These exercise the orchestration logic with real cognitive modules.
The point is to verify that data flows correctly between phases
and that missing modules degrade gracefully.
"""
import tempfile
import time

import pytest


# ── Helpers ──────────────────────────────────────────────────


def _real_self_model():
    from core.cognitive.self_model import SelfModel
    return SelfModel(db_path=tempfile.mktemp(suffix=".db"))


def _real_goal_manager():
    from core.cognitive.goals import GoalManager
    return GoalManager(db_path=tempfile.mktemp(suffix=".db"))


def _real_memory():
    from core.memory.intelligence import MemoryIntelligence
    return MemoryIntelligence(db_path=tempfile.mktemp(suffix=".db"))


def _real_tom():
    from core.cognitive.theory_of_mind import TheoryOfMind
    return TheoryOfMind(db_path=tempfile.mktemp(suffix=".db"))


def _heuristic_planner():
    from core.cognitive.planner import HeuristicPlanBackend, Planner
    return Planner(backends=[HeuristicPlanBackend()])


def _wired_mind(**overrides):
    from core.cognitive.consolidation import Consolidation
    from core.cognitive.curiosity import Curiosity
    from core.cognitive.imagination import Imagination
    from core.cognitive.mind import Mind
    from core.cognitive.reflection import Reflection
    from core.cognitive.skill_registry import SkillRegistry

    sm = overrides.get("self_model") or _real_self_model()
    gm = overrides.get("goal_manager") or _real_goal_manager()
    mem = overrides.get("memory") or _real_memory()
    tom = overrides.get("theory_of_mind") or _real_tom()

    return Mind(
        self_model=sm,
        goal_manager=gm,
        reflection=Reflection(memory=mem, self_model=sm, goal_manager=gm),
        planner=_heuristic_planner(),
        imagination=Imagination(self_model=sm, memory=mem),
        curiosity=Curiosity(
            self_model=sm, goal_manager=gm,
            epsilon=0.99, max_epsilon=1.0,
            rng_seed=1,  # deterministic explore
        ),
        consolidation=Consolidation(memory=mem),
        skill_registry=overrides.get("skill_registry") or SkillRegistry(),
        theory_of_mind=tom,
        memory=mem,
        consolidate_every_n=overrides.get("consolidate_every_n", 10),
    )


# ── CycleReport dataclass ────────────────────────────────────


class TestCycleReport:
    def test_duration_when_finished(self):
        from core.cognitive.mind import CycleReport
        r = CycleReport(cycle_number=1, started_at=100.0, finished_at=102.5)
        assert r.duration_s() == 2.5

    def test_duration_negative_clamped_to_zero(self):
        from core.cognitive.mind import CycleReport
        r = CycleReport(cycle_number=1, started_at=200.0, finished_at=100.0)
        assert r.duration_s() == 0.0

    def test_to_dict_shape(self):
        from core.cognitive.mind import CycleReport
        r = CycleReport(cycle_number=5, started_at=time.time())
        r.finished_at = r.started_at + 1.0
        d = r.to_dict()
        assert d["cycle_number"] == 5
        assert "duration_s" in d
        assert "predictions" in d
        assert "actions_taken" in d

    def test_headline(self):
        from core.cognitive.mind import CycleReport
        r = CycleReport(cycle_number=3, started_at=100.0, finished_at=102.0)
        r.selected_goal_id = "goal_abc1234567890"
        r.actions_taken = [{"kind": "skill"}]
        h = r.headline()
        assert "cycle 3" in h
        assert "acts=1" in h


# ── Empty cycle (no inputs, fresh state) ─────────────────────


class TestEmptyCycle:
    def test_runs_without_crashing(self):
        mind = _wired_mind()
        report = mind.run_cycle()
        assert report.cycle_number == 1
        assert report.error == ""

    def test_no_perception_inputs(self):
        mind = _wired_mind()
        report = mind.run_cycle()
        assert report.perceived_inputs == 0

    def test_no_goal_no_plan(self):
        mind = _wired_mind()
        report = mind.run_cycle()
        # Fresh self-model has no weaknesses → no goals
        assert report.selected_goal_id is None
        assert report.plan is None

    def test_completes_in_under_a_second(self):
        mind = _wired_mind()
        report = mind.run_cycle()
        assert report.duration_s() < 1.0


# ── Cycle with weakness signal ───────────────────────────────


class TestCycleWithWeakness:
    def test_full_pipeline_fires(self):
        mind = _wired_mind()
        # Seed a weakness so all phases activate
        for _ in range(15):
            mind.self_model.assess("engine.flaky", 0.2, source="test")

        report = mind.run_cycle()
        assert report.error == ""
        # Goal pipeline should produce a goal
        assert len(report.goals_proposed) >= 1
        assert report.selected_goal_id is not None
        # Planner should decompose it
        assert report.plan is not None
        assert report.plan.step_count() >= 3
        # Imagination should score it
        assert report.imagined_plan is not None
        # At least one action should be recorded (likely a recommendation
        # since no skill matches)
        assert len(report.actions_taken) >= 1

    def test_action_is_recommendation_when_no_skill(self):
        mind = _wired_mind()
        for _ in range(15):
            mind.self_model.assess("engine.flaky", 0.2, source="test")
        report = mind.run_cycle()
        assert any(a["kind"] == "recommendation" for a in report.actions_taken)

    def test_action_invokes_matching_skill(self):
        mind = _wired_mind()

        # Register + validate a skill named "audit" so it matches the
        # heuristic plan's first step ("Audit recent failures of …")
        mind.skill_registry.propose(
            "audit",
            lambda inputs: {"status": "ok", "audited": True},
        )
        mind.skill_registry.validate(
            "audit",
            [{"input": {}}, {"input": {}}],
            min_accuracy=0.5,
        )

        for _ in range(15):
            mind.self_model.assess("engine.flaky", 0.2, source="test")
        report = mind.run_cycle()
        # The skill should have been invoked
        skill_actions = [a for a in report.actions_taken if a["kind"] == "skill"]
        assert len(skill_actions) >= 1
        assert skill_actions[0]["skill"] == "audit"


# ── Reflection integration ───────────────────────────────────


class TestReflectionPhase:
    def test_reflection_runs_when_memory_has_episodes(self):
        from core.cognitive.consolidation import Consolidation
        from core.cognitive.curiosity import Curiosity
        from core.cognitive.imagination import Imagination
        from core.cognitive.mind import Mind
        from core.cognitive.reflection import Reflection
        from core.cognitive.skill_registry import SkillRegistry

        sm = _real_self_model()
        gm = _real_goal_manager()
        mem = _real_memory()
        tom = _real_tom()

        # Insert raw episodes via raw SQL (skip MemoryIntelligence dedup)
        now = time.time()
        conn = mem._conn()
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                "    features, action, result, score, confidence, tags, "
                "    source_ids, parent_id, timestamp, last_used, last_updated) "
                "VALUES (0, 'episodic', 'action', '{}', '{}', 'pricing', "
                "    '{}', 1.5, 0.3, '[]', '[]', 0, ?, 0, ?)",
                (now - 200 + i, now - 200 + i),
            )
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                "    features, action, result, score, confidence, tags, "
                "    source_ids, parent_id, timestamp, last_used, last_updated) "
                "VALUES (0, 'episodic', 'action', '{}', '{}', 'pricing', "
                "    '{}', 4.5, 0.9, '[]', '[]', 0, ?, 0, ?)",
                (now - 100 + i, now - 100 + i),
            )
        conn.commit()

        mind = Mind(
            self_model=sm,
            goal_manager=gm,
            reflection=Reflection(memory=mem, self_model=sm, goal_manager=gm),
            planner=_heuristic_planner(),
            imagination=Imagination(self_model=sm, memory=mem),
            curiosity=Curiosity(self_model=sm, goal_manager=gm, rng_seed=1),
            consolidation=Consolidation(memory=mem),
            skill_registry=SkillRegistry(),
            theory_of_mind=tom,
            memory=mem,
        )
        report = mind.run_cycle()
        assert report.reflection is not None
        # Should detect an improvement trend
        assert report.reflection.episodes_reviewed >= 5


# ── TheoryOfMind integration ─────────────────────────────────


class TestPredictPhase:
    def test_predicts_for_known_agent(self):
        mind = _wired_mind()
        # Register an agent with a custom belief whose rule matches
        # the "audit" keyword that the heuristic plan uses in its
        # first step ("Audit recent failures of …")
        mind.theory_of_mind.register_agent(
            "seg_anxious", "customer", "Anxious Buyers",
            initial_beliefs={"loss_averse": 0.9},
        )
        # Inject a custom rule via predict_response signature →
        # since predict_response uses default rules, plant a default
        # match instead by triggering "discount" via the goal text
        # NOTE: simpler — register with a "discount" keyword belief
        mind.theory_of_mind.register_agent(
            "seg_discount_lover", "customer", "Discount Lover",
            initial_beliefs={"deal_hunter": 0.9},
        )
        # Make a goal whose plan includes a step with the keyword
        # "discount" — heuristic planner expands "Improve discount"
        # into steps that mention discount
        mind.goal_manager.propose("Improve discount strategy", urgency=0.5)
        report = mind.run_cycle()
        # At least one prediction should fire for the discount-lover
        assert len(report.predictions) >= 1
        assert any(
            p.agent_id == "seg_discount_lover" for p in report.predictions
        )

    def test_no_predictions_when_no_agents(self):
        mind = _wired_mind()
        for _ in range(15):
            mind.self_model.assess("engine.x", 0.2, source="test")
        report = mind.run_cycle()
        assert report.predictions == []


# ── Consolidation cadence ────────────────────────────────────


class TestConsolidationCadence:
    def test_runs_every_n_cycles(self):
        mind = _wired_mind(consolidate_every_n=3)
        # Cycles 1, 2 → no consolidation; cycle 3 → consolidation
        r1 = mind.run_cycle()
        r2 = mind.run_cycle()
        r3 = mind.run_cycle()
        assert r1.consolidation_ran is False
        assert r2.consolidation_ran is False
        assert r3.consolidation_ran is True

    def test_cycle_count_increments(self):
        mind = _wired_mind()
        mind.run_cycle()
        mind.run_cycle()
        mind.run_cycle()
        assert mind.cycle_count() == 3


# ── Graceful degradation: missing modules ───────────────────


class TestDegradation:
    def test_no_planner_no_plan(self):
        from core.cognitive.mind import Mind
        sm = _real_self_model()
        gm = _real_goal_manager()
        for _ in range(15):
            sm.assess("engine.flaky", 0.2, source="test")
        mind = Mind(self_model=sm, goal_manager=gm)
        report = mind.run_cycle()
        # Goal still produced, but no plan because no Planner injected
        assert report.selected_goal_id is not None
        assert report.plan is None

    def test_no_self_model_no_learning(self):
        from core.cognitive.mind import Mind
        mind = Mind(goal_manager=_real_goal_manager())
        report = mind.run_cycle()
        assert report.learning_updates == 0
        assert report.error == ""

    def test_no_modules_at_all(self):
        from core.cognitive.mind import Mind
        mind = Mind()
        report = mind.run_cycle()
        # Should still complete cleanly
        assert report.error == ""
        assert report.cycle_number == 1


# ── Multiple cycles + state evolution ───────────────────────


class TestMultipleCycles:
    def test_three_cycles_completes(self):
        mind = _wired_mind()
        reports = [mind.run_cycle() for _ in range(3)]
        assert all(r.error == "" for r in reports)
        assert [r.cycle_number for r in reports] == [1, 2, 3]

    def test_subsequent_cycles_dont_regenerate_active_goals(self):
        """A weakness should produce 1 goal, not N (one per cycle)."""
        mind = _wired_mind()
        for _ in range(15):
            mind.self_model.assess("engine.dup_test", 0.2, source="test")

        first = mind.run_cycle()
        second = mind.run_cycle()
        third = mind.run_cycle()

        # Goals should not pile up — both propose_from_self_model and
        # Curiosity.propose_exploration_goal dedupe against active
        # goals. We expect at most one practice goal (from SelfModel)
        # and at most one exploration goal (from Curiosity), regardless
        # of how many cycles ran.
        all_goals = mind.goal_manager.list_goals()
        practice_goals = [
            g for g in all_goals
            if g.get("source") == "self_model.weakness:engine.dup_test"
        ]
        explore_goals = [
            g for g in all_goals
            if g.get("source") == "curiosity:engine.dup_test"
        ]
        assert len(practice_goals) == 1
        assert len(explore_goals) <= 1


# ── Deliberation gate (act phase) ────────────────────────────


def _act_with(
    *,
    imagined_score=1.0,
    imagined_confidence=1.0,
    predictions=None,
    plan_steps=("ship the thing",),
):
    """Run just the act phase against a hand-built context+report."""
    from core.cognitive.imagination import ImaginedPlan
    from core.cognitive.mind import CycleContext, CycleReport, Mind

    # Simple plan duck-type — _phase_act only needs .steps and each
    # step's .description.
    class _Step:
        def __init__(self, d): self.description = d

    class _Plan:
        steps = [_Step(d) for d in plan_steps]

    mind = Mind()  # no modules — act phase doesn't need them for this
    ctx = CycleContext(cycle_number=1, started_at=time.time())
    ctx.perception["plan"] = _Plan()
    report = CycleReport(cycle_number=1, started_at=time.time())
    report.imagined_plan = ImaginedPlan(
        plan_what="x",
        backend="heuristic",
        expected_score=imagined_score,
        overall_confidence=imagined_confidence,
    )
    if predictions is not None:
        report.predictions = list(predictions)
    mind._phase_act(ctx, report)
    return report


def _fake_prediction(agent_id, response, confidence):
    from core.cognitive.theory_of_mind import Prediction
    return Prediction(
        agent_id=agent_id,
        action_proposed="x",
        predicted_response=response,
        confidence=confidence,
    )


class TestActDeliberationGate:
    def test_proceeds_when_signals_are_positive(self):
        report = _act_with(imagined_score=0.8, imagined_confidence=0.8)
        assert report.actions_taken
        # Default no-skill path → "recommendation"
        assert report.actions_taken[0]["kind"] == "recommendation"

    def test_abstains_on_low_imagined_score(self):
        report = _act_with(imagined_score=0.1, imagined_confidence=0.9)
        assert len(report.actions_taken) == 1
        a = report.actions_taken[0]
        assert a["kind"] == "abstain"
        assert "imagination pessimistic" in a["reason"]
        assert a["expected_score"] == 0.1

    def test_abstains_on_low_imagined_confidence(self):
        report = _act_with(imagined_score=0.9, imagined_confidence=0.1)
        assert report.actions_taken[0]["kind"] == "abstain"

    def test_pauses_on_negative_high_confidence_prediction(self):
        report = _act_with(
            imagined_score=0.8, imagined_confidence=0.8,
            predictions=[
                _fake_prediction("vip_customer", "will refuse the offer", 0.9),
            ],
        )
        a = report.actions_taken[0]
        assert a["kind"] == "pause"
        assert a["agent_id"] == "vip_customer"
        assert a["prediction_confidence"] == 0.9

    def test_ignores_low_confidence_negative_prediction(self):
        report = _act_with(
            imagined_score=0.8, imagined_confidence=0.8,
            predictions=[
                _fake_prediction("x", "may refuse", 0.3),
            ],
        )
        # Below pause threshold → falls through to recommendation
        assert report.actions_taken[0]["kind"] == "recommendation"

    def test_ignores_positive_high_confidence_prediction(self):
        report = _act_with(
            imagined_score=0.8, imagined_confidence=0.8,
            predictions=[
                _fake_prediction("x", "delighted, will buy more", 0.95),
            ],
        )
        assert report.actions_taken[0]["kind"] == "recommendation"

    def test_imagination_blocks_before_predictions_checked(self):
        # If imagination fails the gate, we should abstain even when
        # there's also a negative prediction (single failure path).
        report = _act_with(
            imagined_score=0.05, imagined_confidence=0.9,
            predictions=[
                _fake_prediction("x", "will reject", 0.95),
            ],
        )
        assert report.actions_taken[0]["kind"] == "abstain"


# ── Cycle history + calibration loop ─────────────────────────


def _seeded_prev_cycle(
    *,
    imagined_score=0.8,
    imagined_confidence=0.8,
    skill_results=None,
    actions_extra=None,
    predictions=None,
):
    """Build a CycleReport that mimics one that just finished, so a
    fresh cycle can calibrate against it."""
    from core.cognitive.imagination import ImaginedPlan
    from core.cognitive.mind import CycleReport

    rep = CycleReport(cycle_number=1, started_at=time.time())
    rep.imagined_plan = ImaginedPlan(
        plan_what="x",
        backend="heuristic",
        expected_score=imagined_score,
        overall_confidence=imagined_confidence,
    )
    rep.actions_taken = []
    for i, status in enumerate(skill_results or []):
        rep.actions_taken.append({
            "kind": "skill",
            "skill": f"skill_{i}",
            "result": {"status": status},
        })
    if actions_extra:
        rep.actions_taken.extend(actions_extra)
    if predictions:
        rep.predictions = list(predictions)
    rep.finished_at = time.time()
    return rep


class TestCycleHistory:
    def test_history_starts_empty(self):
        from core.cognitive.mind import Mind
        m = Mind()
        assert m.last_cycles() == []
        assert m.previous_cycle() is None

    def test_run_cycle_appends_history(self):
        m = _wired_mind()
        m.run_cycle()
        m.run_cycle()
        assert len(m.last_cycles()) == 2
        assert m.previous_cycle() is not None

    def test_history_is_bounded(self):
        from core.cognitive.mind import Mind
        m = Mind(cycle_history_size=3)
        for _ in range(7):
            m.run_cycle()  # Mind() with no modules → trivial cycles
        assert len(m.last_cycles(100)) == 3

    def test_last_cycles_returns_newest_last(self):
        m = _wired_mind()
        for _ in range(3):
            m.run_cycle()
        cycles = m.last_cycles(2)
        assert len(cycles) == 2
        assert cycles[-1].cycle_number > cycles[0].cycle_number


class TestImaginationCalibration:
    def test_perfect_when_score_matches_success_rate(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle(
            imagined_score=1.0,
            skill_results=["ok", "ok"],
        )
        cal = m._calibrate_imagination(prev)
        assert cal == 1.0

    def test_low_when_overconfident(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle(
            imagined_score=0.9,
            skill_results=["error", "error"],  # 0% success
        )
        # imagined 0.9 vs actual 0.0 → error 0.9 → calibration 0.1
        cal = m._calibrate_imagination(prev)
        assert cal == pytest.approx(0.1, abs=1e-6)

    def test_partial_success(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle(
            imagined_score=0.5,
            skill_results=["ok", "error"],  # 50% success
        )
        cal = m._calibrate_imagination(prev)
        assert cal == 1.0  # perfect — predicted 0.5, actual 0.5

    def test_returns_none_without_imagination(self):
        from core.cognitive.mind import Mind, CycleReport
        m = Mind()
        rep = CycleReport(cycle_number=1, started_at=time.time())
        assert m._calibrate_imagination(rep) is None

    def test_credits_abstain_modestly(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle(
            imagined_score=0.1,
            skill_results=None,
            actions_extra=[{"kind": "abstain", "reason": "imagination pessimistic"}],
        )
        cal = m._calibrate_imagination(prev)
        assert cal == 0.6

    def test_returns_none_when_no_actions_or_abstain(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle(imagined_score=0.5)  # no actions
        assert m._calibrate_imagination(prev) is None


class TestPredictionCalibration:
    def test_returns_none_without_predictions(self):
        from core.cognitive.mind import Mind
        m = Mind()
        prev = _seeded_prev_cycle()
        assert m._calibrate_predictions(prev) is None

    def test_pause_credited_when_no_skills_ran(self):
        from core.cognitive.mind import Mind
        from core.cognitive.theory_of_mind import Prediction
        m = Mind()
        prev = _seeded_prev_cycle(
            actions_extra=[{"kind": "pause", "reason": "neg pred"}],
            predictions=[Prediction(
                agent_id="x", action_proposed="y",
                predicted_response="will reject", confidence=0.9,
            )],
        )
        assert m._calibrate_predictions(prev) == 0.55

    def test_skill_success_rate_used_when_skills_ran(self):
        from core.cognitive.mind import Mind
        from core.cognitive.theory_of_mind import Prediction
        m = Mind()
        prev = _seeded_prev_cycle(
            skill_results=["ok", "ok", "error"],  # 2/3
            predictions=[Prediction(
                agent_id="x", action_proposed="y",
                predicted_response="indifferent", confidence=0.4,
            )],
        )
        cal = m._calibrate_predictions(prev)
        assert cal == pytest.approx(2/3, abs=1e-6)


class TestCalibrationIntegratesWithSelfModel:
    def test_calibrate_phase_writes_to_self_model(self):
        m = _wired_mind()
        # Inject a hand-built previous cycle into history
        prev = _seeded_prev_cycle(
            imagined_score=0.9,
            skill_results=["ok", "ok"],
        )
        m._cycle_history.append(prev)
        # Run a fresh cycle — calibrate phase will run
        m.run_cycle()
        cap = m.self_model.get_capability("mind.imagination_calibration")
        assert cap is not None
        # imagined 0.9 vs actual 1.0 → error 0.1 → calibration 0.9
        assert cap["score"] == pytest.approx(0.9, abs=0.01)

    def test_calibration_snapshot_after_run(self):
        m = _wired_mind()
        prev = _seeded_prev_cycle(
            imagined_score=0.5, skill_results=["ok", "error"],
        )
        m._cycle_history.append(prev)
        m.run_cycle()
        snap = m.calibration_snapshot()
        assert snap["last_imagination_calibration"] == pytest.approx(1.0)
        assert snap["history_size"] >= 2

    def test_first_cycle_does_not_calibrate(self):
        m = _wired_mind()
        m.run_cycle()
        cap = m.self_model.get_capability("mind.imagination_calibration")
        assert cap is None  # nothing to calibrate against


# ── Goal lifecycle phase ─────────────────────────────────────


def _build_lifecycle_report(
    *,
    selected_goal_id,
    skill_results=None,
    abstain=False,
    pause=False,
):
    """Tiny CycleReport factory for direct _phase_goal_lifecycle calls."""
    from core.cognitive.mind import CycleReport
    rep = CycleReport(cycle_number=1, started_at=time.time())
    rep.selected_goal_id = selected_goal_id
    if skill_results:
        for i, status in enumerate(skill_results):
            rep.actions_taken.append({
                "kind": "skill", "skill": f"s{i}",
                "result": {"status": status},
            })
    if abstain:
        rep.actions_taken.append({"kind": "abstain", "reason": "test"})
    if pause:
        rep.actions_taken.append({"kind": "pause", "reason": "test"})
    return rep


class TestGoalLifecycle:
    def test_no_goal_manager_is_noop(self):
        from core.cognitive.mind import Mind, CycleContext
        m = Mind()
        ctx = CycleContext(cycle_number=1, started_at=time.time())
        rep = _build_lifecycle_report(selected_goal_id="g1")
        m._phase_goal_lifecycle(ctx, rep)  # should not raise

    def test_no_selected_goal_is_noop(self):
        m = _wired_mind()
        from core.cognitive.mind import CycleContext
        ctx = CycleContext(cycle_number=1, started_at=time.time())
        rep = _build_lifecycle_report(selected_goal_id=None)
        m._phase_goal_lifecycle(ctx, rep)
        assert m._goal_strikes == {}

    def test_successful_skill_bumps_progress(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Do thing", urgency=0.5)
        ctx = _ctx()
        rep = _build_lifecycle_report(selected_goal_id=gid, skill_results=["ok"])
        m._phase_goal_lifecycle(ctx, rep)
        goal = m.goal_manager.get(gid)
        assert goal["progress"] == pytest.approx(0.25, abs=1e-6)
        assert goal["state"] != "completed"

    def test_four_successes_complete_goal(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Do thing", urgency=0.5)
        ctx = _ctx()
        for _ in range(4):
            rep = _build_lifecycle_report(
                selected_goal_id=gid, skill_results=["ok"],
            )
            m._phase_goal_lifecycle(ctx, rep)
        goal = m.goal_manager.get(gid)
        assert goal["state"] == "completed"
        assert goal["progress"] == pytest.approx(1.0)
        # Strikes cleared after completion
        assert gid not in m._goal_strikes

    def test_three_abstains_abandon_goal(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Doomed", urgency=0.5)
        ctx = _ctx()
        for _ in range(3):
            rep = _build_lifecycle_report(selected_goal_id=gid, abstain=True)
            m._phase_goal_lifecycle(ctx, rep)
        goal = m.goal_manager.get(gid)
        assert goal["state"] == "abandoned"
        assert gid not in m._goal_strikes

    def test_three_skill_failures_fail_goal(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Broken", urgency=0.5)
        ctx = _ctx()
        for _ in range(3):
            rep = _build_lifecycle_report(
                selected_goal_id=gid, skill_results=["error"],
            )
            m._phase_goal_lifecycle(ctx, rep)
        goal = m.goal_manager.get(gid)
        assert goal["state"] == "failed"
        assert gid not in m._goal_strikes

    def test_success_resets_failure_strikes(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Flaky", urgency=0.5)
        ctx = _ctx()
        # 2 failures, then a success — failure counter should reset
        for _ in range(2):
            m._phase_goal_lifecycle(
                ctx,
                _build_lifecycle_report(selected_goal_id=gid, skill_results=["error"]),
            )
        m._phase_goal_lifecycle(
            ctx,
            _build_lifecycle_report(selected_goal_id=gid, skill_results=["ok"]),
        )
        assert m._goal_strikes[gid]["skill_fail"] == 0
        # And one more failure should not yet retire it
        m._phase_goal_lifecycle(
            ctx,
            _build_lifecycle_report(selected_goal_id=gid, skill_results=["error"]),
        )
        assert m.goal_manager.get(gid)["state"] != "failed"

    def test_pause_and_recommendation_are_neutral(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Quiet", urgency=0.5)
        ctx = _ctx()
        for _ in range(5):
            m._phase_goal_lifecycle(
                ctx, _build_lifecycle_report(selected_goal_id=gid, pause=True),
            )
        goal = m.goal_manager.get(gid)
        assert goal["state"] not in ("completed", "abandoned", "failed")
        assert goal["progress"] == pytest.approx(0.0)

    def test_strikes_tracked_per_goal(self):
        m = _wired_mind()
        gid_a = m.goal_manager.propose("A", urgency=0.5)
        gid_b = m.goal_manager.propose("B", urgency=0.5)
        ctx = _ctx()
        # 2 abstains on A, 2 abstains on B — neither retired yet
        for gid in (gid_a, gid_b, gid_a, gid_b):
            m._phase_goal_lifecycle(
                ctx, _build_lifecycle_report(selected_goal_id=gid, abstain=True),
            )
        assert m.goal_manager.get(gid_a)["state"] not in ("abandoned", "failed", "completed")
        assert m.goal_manager.get(gid_b)["state"] not in ("abandoned", "failed", "completed")
        assert m._goal_strikes[gid_a]["abstain"] == 2
        assert m._goal_strikes[gid_b]["abstain"] == 2

    def test_partial_skill_failure_counts_as_failure(self):
        m = _wired_mind()
        gid = m.goal_manager.propose("Partial", urgency=0.5)
        ctx = _ctx()
        # Mixed result counts as a strike (not all_ok)
        m._phase_goal_lifecycle(
            ctx, _build_lifecycle_report(
                selected_goal_id=gid, skill_results=["ok", "error"],
            ),
        )
        assert m._goal_strikes[gid]["skill_fail"] == 1
        assert m.goal_manager.get(gid)["progress"] == pytest.approx(0.0)


def _ctx():
    from core.cognitive.mind import CycleContext
    return CycleContext(cycle_number=1, started_at=time.time())


# ── LEARN phase writes episodes to memory ────────────────────


class _RecordingMemory:
    """Captures every memory.create() call so we can verify Mind
    actually persists episodes during LEARN."""

    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return len(self.calls)  # fake memory id


class TestLearnPhaseWritesMemory:
    def test_no_memory_means_no_call(self):
        from core.cognitive.mind import Mind, CycleReport
        m = Mind(memory=None, self_model=None)
        rep = CycleReport(cycle_number=1, started_at=time.time())
        # Should not raise.
        assert m._record_cycle_episode(rep) is False

    def test_memory_without_create_method(self):
        from core.cognitive.mind import Mind, CycleReport
        m = Mind(memory=object())  # no .create
        rep = CycleReport(cycle_number=1, started_at=time.time())
        assert m._record_cycle_episode(rep) is False

    def test_skill_success_records_high_score(self):
        from core.cognitive.mind import Mind, CycleReport
        mem = _RecordingMemory()
        m = Mind(memory=mem)
        rep = CycleReport(cycle_number=7, started_at=time.time())
        rep.actions_taken = [
            {"kind": "skill", "skill": "ship", "result": {"status": "ok"}},
        ]
        rep.finished_at = time.time()
        assert m._record_cycle_episode(rep) is True
        assert len(mem.calls) == 1
        call = mem.calls[0]
        assert call["category"] == "mind"
        assert call["score"] == 4.5  # success bumps to 4.5
        assert "skill" in call["tags"]
        assert call["content"]["cycle_number"] == 7

    def test_skill_failure_records_low_score(self):
        from core.cognitive.mind import Mind, CycleReport
        mem = _RecordingMemory()
        m = Mind(memory=mem)
        rep = CycleReport(cycle_number=1, started_at=time.time())
        rep.actions_taken = [
            {"kind": "skill", "skill": "x", "result": {"status": "error"}},
        ]
        m._record_cycle_episode(rep)
        assert mem.calls[0]["score"] == 1.5

    def test_abstain_records_neutral_low_score(self):
        from core.cognitive.mind import Mind, CycleReport
        mem = _RecordingMemory()
        m = Mind(memory=mem)
        rep = CycleReport(cycle_number=1, started_at=time.time())
        rep.actions_taken = [{"kind": "abstain", "reason": "test"}]
        m._record_cycle_episode(rep)
        assert mem.calls[0]["score"] == 2.0
        assert "abstain" in mem.calls[0]["tags"]

    def test_error_drives_score_to_floor(self):
        from core.cognitive.mind import Mind, CycleReport
        mem = _RecordingMemory()
        m = Mind(memory=mem)
        rep = CycleReport(cycle_number=1, started_at=time.time())
        rep.error = "boom"
        rep.actions_taken = [
            {"kind": "skill", "skill": "x", "result": {"status": "ok"}},
        ]
        m._record_cycle_episode(rep)
        assert mem.calls[0]["score"] == 1.0

    def test_memory_create_failure_does_not_crash(self):
        from core.cognitive.mind import Mind, CycleReport

        class _Boom:
            def create(self, **k):
                raise RuntimeError("disk full")

        m = Mind(memory=_Boom())
        rep = CycleReport(cycle_number=1, started_at=time.time())
        rep.actions_taken = [{"kind": "abstain"}]
        assert m._record_cycle_episode(rep) is False
        assert any("memory.create" in n for n in rep.notes)

    def test_learn_phase_records_episode_without_self_model(self):
        # Regression: previously _phase_learn early-returned when
        # self_model was None, so memory was never written even
        # though the backend was wired. Now the three paths run
        # independently.
        from core.cognitive.mind import Mind, CycleReport, CycleContext
        mem = _RecordingMemory()
        m = Mind(memory=mem, self_model=None)
        rep = CycleReport(cycle_number=2, started_at=time.time())
        rep.actions_taken = [
            {"kind": "skill", "skill": "x", "result": {"status": "ok"}},
        ]
        rep.finished_at = time.time()
        ctx = CycleContext(cycle_number=2, started_at=time.time())
        m._phase_learn(ctx, rep)
        assert len(mem.calls) == 1
        assert rep.learning_updates == 1

    def test_full_learn_with_self_model_records_episode(self):
        # With a self_model wired, the LEARN phase should write to
        # memory at the end.
        from core.cognitive.mind import Mind, CycleReport, CycleContext
        mem = _RecordingMemory()
        sm = _real_self_model()
        m = Mind(memory=mem, self_model=sm)
        rep = CycleReport(cycle_number=3, started_at=time.time())
        rep.actions_taken = [
            {"kind": "skill", "skill": "x", "result": {"status": "ok"}},
        ]
        rep.finished_at = time.time()
        ctx = CycleContext(cycle_number=3, started_at=time.time())
        m._phase_learn(ctx, rep)
        assert len(mem.calls) == 1


class TestSingleton:
    def test_get_mind_caches(self):
        from core.cognitive import mind as mod
        mod._instance = None
        a = mod.get_mind()
        b = mod.get_mind()
        assert a is b

    def test_build_default_mind_returns_a_mind(self):
        from core.cognitive.mind import build_default_mind, Mind
        m = build_default_mind()
        assert isinstance(m, Mind)
        # All 9 modules should be wired
        assert m.self_model is not None
        assert m.goal_manager is not None
        assert m.reflection is not None
        assert m.planner is not None
        assert m.imagination is not None
        assert m.curiosity is not None
        assert m.skill_registry is not None
        assert m.theory_of_mind is not None
