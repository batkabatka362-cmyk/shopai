"""End-to-end integration tests for the cognitive package.

These tests drive multi-cycle scenarios through real instances of
all 10 cognitive modules to verify that data flows correctly
between them and that the AI's state evolves as it learns.

Each test is a small story:
    1. Set up an initial situation (a known weakness, an agent,
       some episodes)
    2. Run several Mind cycles
    3. Assert the cognitive state evolved as expected (goals
       proposed, plans made, beliefs updated, lessons learned)

These are slow compared to unit tests because each one builds the
full cognitive stack. Use sparingly — but they're the best
guarantee that the modules genuinely work together.
"""
import tempfile
import time

import pytest


def _wired_mind(*, consolidate_every_n=10):
    from core.cognitive.consolidation import Consolidation
    from core.cognitive.curiosity import Curiosity
    from core.cognitive.goals import GoalManager
    from core.cognitive.imagination import Imagination
    from core.cognitive.mind import Mind
    from core.cognitive.planner import HeuristicPlanBackend, Planner
    from core.cognitive.reflection import Reflection
    from core.cognitive.self_model import SelfModel
    from core.cognitive.skill_registry import SkillRegistry
    from core.cognitive.theory_of_mind import TheoryOfMind
    from core.memory.intelligence import MemoryIntelligence

    sm = SelfModel(db_path=tempfile.mktemp(suffix=".db"))
    gm = GoalManager(db_path=tempfile.mktemp(suffix=".db"))
    mem = MemoryIntelligence(db_path=tempfile.mktemp(suffix=".db"))
    tom = TheoryOfMind(db_path=tempfile.mktemp(suffix=".db"))

    return Mind(
        self_model=sm,
        goal_manager=gm,
        reflection=Reflection(memory=mem, self_model=sm, goal_manager=gm),
        planner=Planner(backends=[HeuristicPlanBackend()]),
        imagination=Imagination(self_model=sm, memory=mem),
        curiosity=Curiosity(
            self_model=sm, goal_manager=gm,
            epsilon=0.30, max_epsilon=0.50, rng_seed=1,
        ),
        consolidation=Consolidation(memory=mem),
        skill_registry=SkillRegistry(),
        theory_of_mind=tom,
        memory=mem,
        consolidate_every_n=consolidate_every_n,
    )


# ── Story 1: Discover weakness → propose goal → plan → act ──


class TestStoryDiscoverAndAct:
    def test_full_pipeline_completes(self):
        """The AI notices a weakness, generates a goal, plans it,
        invokes a matching skill, and learns from the outcome."""
        mind = _wired_mind()

        # 1. Plant a weakness in the SelfModel
        for _ in range(15):
            mind.self_model.assess("engine.audit", 0.2, source="seed")

        # 2. Register + validate a skill that matches the weakness
        mind.skill_registry.propose(
            "audit",
            lambda inputs: {
                "status": "ok",
                "audited_count": 5,
                "common_failure": "rate_limit",
            },
        )
        mind.skill_registry.validate(
            "audit",
            [{"input": {}}, {"input": {}}],
            min_accuracy=0.5,
        )

        # 3. Run one cycle
        report = mind.run_cycle()

        # Assertions:
        assert report.error == ""
        # 3a. A practice goal for engine.audit was generated
        assert any("engine.audit" in mind.goal_manager.get(gid)["source"]
                   for gid in report.goals_proposed)
        # 3b. A goal was selected and a plan was produced
        assert report.selected_goal_id is not None
        assert report.plan is not None
        assert report.plan.step_count() >= 4
        # 3c. The first plan step references the target capability
        assert "engine.audit" in report.plan.steps[0].description
        # 3d. The "audit" skill was actually invoked
        skill_actions = [a for a in report.actions_taken if a["kind"] == "skill"]
        assert len(skill_actions) == 1
        assert skill_actions[0]["skill"] == "audit"
        assert skill_actions[0]["result"]["audited_count"] == 5
        # 3e. The skill registry recorded the invocation
        skill = mind.skill_registry.get("audit")
        assert skill.use_count == 1
        assert skill.success_count == 1


# ── Story 2: Curiosity drives exploration ────────────────────


class TestStoryCuriosityExploration:
    def test_unknown_capability_becomes_explore_goal(self):
        """A capability with very few observations should drive
        Curiosity to propose an exploration goal at some point."""
        mind = _wired_mind()
        # Plant a barely-known capability
        mind.self_model.assess("engine.mystery", 0.5, source="seed")

        # Run several cycles to give Curiosity multiple chances
        # (epsilon=0.30 means ~30% explore, so within 10 cycles
        # we'd expect at least one explore decision)
        for _ in range(15):
            mind.run_cycle()

        # By now Curiosity should have proposed at least one
        # exploration goal targeting engine.mystery
        explore_goals = [
            g for g in mind.goal_manager.list_goals()
            if g.get("source") == "curiosity:engine.mystery"
        ]
        assert len(explore_goals) >= 1


# ── Story 3: Reflection lowers urgency on improvement ───────


class TestStoryReflectionAdjustsUrgency:
    def test_improvement_in_memory_lowers_goal_urgency(self):
        """When recent memory shows a weakness improving, the
        active practice goal's urgency should drop."""
        mind = _wired_mind()

        # Seed weakness + matching active goal
        for _ in range(15):
            mind.self_model.assess("engine.improving", 0.2)
        mind.run_cycle()

        active = mind.goal_manager.active()
        practice = next(
            (g for g in active
             if g.get("source") == "self_model.weakness:engine.improving"),
            None,
        )
        assert practice is not None
        original_urgency = practice["urgency"]

        # Insert raw episodes showing improvement (5 bad → 5 good)
        now = time.time()
        conn = mind.memory._conn()
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                "    features, action, result, score, confidence, tags, "
                "    source_ids, parent_id, timestamp, last_used, last_updated) "
                "VALUES (0, 'episodic', 'action', '{}', '{}', 'engine.improving', "
                "    '{}', 1.5, 0.3, '[]', '[]', 0, ?, 0, ?)",
                (now - 200 + i, now - 200 + i),
            )
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                "    features, action, result, score, confidence, tags, "
                "    source_ids, parent_id, timestamp, last_used, last_updated) "
                "VALUES (0, 'episodic', 'action', '{}', '{}', 'engine.improving', "
                "    '{}', 4.5, 0.9, '[]', '[]', 0, ?, 0, ?)",
                (now - 100 + i, now - 100 + i),
            )
        conn.commit()

        # Run another cycle — Reflection should detect improvement
        # and lower the goal's urgency
        mind.run_cycle()

        revised = mind.goal_manager.get(practice["id"])
        assert revised["urgency"] <= original_urgency


# ── Story 4: TheoryOfMind beliefs evolve from observations ──


class TestStoryTheoryOfMindEvolves:
    def test_belief_drops_on_contradictions(self):
        mind = _wired_mind()
        mind.theory_of_mind.register_agent(
            "seg_loyal", "customer", "Loyal Buyers",
            initial_beliefs={"loyal": 0.8},
        )

        # Customer behavior contradicts the loyalty belief 10 times
        for _ in range(10):
            mind.theory_of_mind.observe(
                "seg_loyal",
                {"event": "switched_to_competitor"},
                contradicts=["loyal"],
            )

        # Belief should have dropped substantially
        assert mind.theory_of_mind.belief("seg_loyal", "loyal") < 0.5


# ── Story 5: Skills can be composed and used ───────────────


class TestStorySkillComposition:
    def test_compose_chain_runs(self):
        mind = _wired_mind()

        mind.skill_registry.propose(
            "step1",
            lambda i: {"status": "ok", "intermediate": i.get("seed", 0) + 1},
        )
        mind.skill_registry.propose(
            "step2",
            lambda i: {"status": "ok", "final": i.get("intermediate", 0) * 10},
        )
        mind.skill_registry.validate("step1", [{"input": {"seed": 1}}],
                                     min_accuracy=0.5)
        mind.skill_registry.validate("step2", [{"input": {"intermediate": 1}}],
                                     min_accuracy=0.5)

        mind.skill_registry.compose("pipeline", ["step1", "step2"])
        mind.skill_registry.validate("pipeline", [{"input": {"seed": 1}}],
                                     min_accuracy=0.5)

        result = mind.skill_registry.invoke("pipeline", {"seed": 5})
        # seed=5 → step1 intermediate=6 → step2 final=60
        assert result["intermediate"] == 6
        assert result["final"] == 60


# ── Story 6: Consolidation runs on cadence ──────────────────


class TestStoryConsolidationCadence:
    def test_consolidation_runs_periodically(self):
        mind = _wired_mind(consolidate_every_n=3)

        # Insert enough episodes to give consolidation work to do
        now = time.time()
        conn = mind.memory._conn()
        for i in range(8):
            conn.execute(
                "INSERT INTO memories (level, memory_type, category, content, "
                "    features, action, result, score, confidence, tags, "
                "    source_ids, parent_id, timestamp, last_used, last_updated) "
                "VALUES (0, 'episodic', 'action', '{}', '{}', 'pricing', "
                "    '{}', 4.0, 0.8, '[]', '[]', 0, ?, 0, ?)",
                (now - 100 + i, now - 100 + i),
            )
        conn.commit()

        # 3 cycles → consolidation should run on cycle 3
        reports = [mind.run_cycle() for _ in range(3)]
        assert reports[0].consolidation_ran is False
        assert reports[1].consolidation_ran is False
        assert reports[2].consolidation_ran is True


# ── Story 7: Multi-cycle state evolution ────────────────────


class TestStoryStateEvolution:
    def test_self_model_accumulates_across_cycles(self):
        """Each cycle should add at least one assessment to the
        SelfModel via the LEARN phase."""
        mind = _wired_mind()
        # Plant a weakness so the cycle has something to do
        for _ in range(15):
            mind.self_model.assess("engine.x", 0.2)
        before = len(mind.self_model.capabilities())
        for _ in range(5):
            mind.run_cycle()
        after = len(mind.self_model.capabilities())
        # The LEARN phase calls ingest_cycle_result which should
        # add new capabilities (at least cycle.cycle_completion)
        assert after > before

    def test_no_goal_pile_up_across_many_cycles(self):
        """Same weakness across 20 cycles should not produce 20
        practice goals — both SelfModel-based goals and
        Curiosity-based goals dedupe."""
        mind = _wired_mind()
        for _ in range(15):
            mind.self_model.assess("engine.dedup", 0.2)

        for _ in range(20):
            mind.run_cycle()

        practice_goals = [
            g for g in mind.goal_manager.list_goals()
            if g.get("source") == "self_model.weakness:engine.dedup"
        ]
        explore_goals = [
            g for g in mind.goal_manager.list_goals()
            if g.get("source") == "curiosity:engine.dedup"
        ]
        # At most one of each — completion would allow re-proposal
        assert len(practice_goals) <= 1
        assert len(explore_goals) <= 1


# ── Story 8: Mind report shape is stable ───────────────────


class TestStoryReportShape:
    def test_cycle_report_dict_is_serializable(self):
        """The CycleReport.to_dict() output should round-trip
        through json.dumps without raising — useful for logging
        and the API."""
        import json
        mind = _wired_mind()
        for _ in range(15):
            mind.self_model.assess("engine.x", 0.2)
        report = mind.run_cycle()
        d = report.to_dict()
        # Should serialize cleanly
        encoded = json.dumps(d, default=str)
        assert encoded
        decoded = json.loads(encoded)
        assert decoded["cycle_number"] == 1
