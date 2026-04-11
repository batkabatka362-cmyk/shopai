"""Tests for GoalManager — self-directed goal generation + lifecycle."""
import tempfile
import time

import pytest


def _fresh():
    from core.cognitive.goals import GoalManager
    return GoalManager(db_path=tempfile.mktemp(suffix=".db"))


class TestPropose:
    def test_proposes_with_defaults(self):
        gm = _fresh()
        gid = gm.propose("Improve conversion rate")
        assert gid.startswith("goal_")
        g = gm.get(gid)
        assert g is not None
        assert g["what"] == "Improve conversion rate"
        assert g["state"] == "proposed"
        assert 0.0 < g["priority"] < 1.0

    def test_empty_what_raises(self):
        gm = _fresh()
        with pytest.raises(ValueError):
            gm.propose("")
        with pytest.raises(ValueError):
            gm.propose("   ")

    def test_stores_scoring_inputs(self):
        gm = _fresh()
        gid = gm.propose(
            "X", impact=0.9, urgency=0.8, confidence=0.7, cost=0.1,
        )
        g = gm.get(gid)
        assert g["impact"] == pytest.approx(0.9)
        assert g["urgency"] == pytest.approx(0.8)
        assert g["confidence"] == pytest.approx(0.7)
        assert g["cost"] == pytest.approx(0.1)

    def test_clamps_out_of_range_scores(self):
        gm = _fresh()
        gid = gm.propose("X", impact=1.5, cost=-0.3)
        g = gm.get(gid)
        assert g["impact"] == 1.0
        assert g["cost"] == 0.0

    def test_non_numeric_score_falls_back_to_half(self):
        gm = _fresh()
        gid = gm.propose("X", impact="not a number")  # type: ignore
        assert gm.get(gid)["impact"] == 0.5

    def test_priority_higher_for_high_impact_low_cost(self):
        gm = _fresh()
        big = gm.propose("big", impact=1.0, urgency=1.0, confidence=1.0, cost=0.0)
        small = gm.propose("small", impact=0.1, urgency=0.1, confidence=0.1, cost=1.0)
        assert gm.get(big)["priority"] > gm.get(small)["priority"]


class TestLifecycleTransitions:
    def test_full_lifecycle_completion(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.activate(gid)
        assert gm.get(gid)["state"] == "active"
        gm.start(gid)
        assert gm.get(gid)["state"] == "in_progress"
        gm.complete(gid, result_notes="done")
        g = gm.get(gid)
        assert g["state"] == "completed"
        assert g["progress"] == pytest.approx(1.0)
        assert g["result_notes"] == "done"
        assert g["completed_at"] > 0

    def test_fail_records_reason(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.fail(gid, reason="out of budget")
        g = gm.get(gid)
        assert g["state"] == "failed"
        assert g["result_notes"] == "out of budget"

    def test_abandon(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.abandon(gid, reason="no longer relevant")
        assert gm.get(gid)["state"] == "abandoned"

    def test_transitions_logged(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.activate(gid)
        gm.start(gid)
        gm.complete(gid)
        events = gm.events(gid)
        event_types = [e["event_type"] for e in events]
        # Most recent first → completed, in_progress, active, proposed
        assert "state_change" in event_types

    def test_same_state_is_noop(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.activate(gid)
        events_before = gm.events(gid)
        gm.activate(gid)  # no-op
        events_after = gm.events(gid)
        assert len(events_after) == len(events_before)

    def test_transition_unknown_goal_is_safe(self):
        gm = _fresh()
        gm.activate("ghost_goal_id")  # should not raise
        gm.complete("ghost_goal_id")


class TestProgress:
    def test_update_progress_clamped(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.update_progress(gid, 0.5)
        assert gm.get(gid)["progress"] == pytest.approx(0.5)
        gm.update_progress(gid, 2.0)  # clamped
        assert gm.get(gid)["progress"] == pytest.approx(1.0)

    def test_progress_event_logged(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.update_progress(gid, 0.25, notes="halfway through research")
        gm.update_progress(gid, 0.75)
        events = [e for e in gm.events(gid) if e["event_type"] == "progress"]
        assert len(events) == 2

    def test_progress_on_ghost_goal_is_noop(self):
        gm = _fresh()
        gm.update_progress("ghost", 0.5)  # no crash


class TestRevise:
    def test_revise_updates_priority(self):
        gm = _fresh()
        gid = gm.propose("X", impact=0.5, cost=0.5)
        p1 = gm.get(gid)["priority"]
        gm.revise(gid, impact=1.0, cost=0.0, why="re-evaluated")
        p2 = gm.get(gid)["priority"]
        assert p2 > p1

    def test_partial_revision_keeps_others(self):
        gm = _fresh()
        gid = gm.propose("X", impact=0.8, urgency=0.3, cost=0.2)
        gm.revise(gid, cost=0.9)
        g = gm.get(gid)
        assert g["impact"] == pytest.approx(0.8)
        assert g["urgency"] == pytest.approx(0.3)
        assert g["cost"] == pytest.approx(0.9)

    def test_revise_logs_event(self):
        gm = _fresh()
        gid = gm.propose("X")
        gm.revise(gid, impact=0.9, why="new evidence")
        events = [e for e in gm.events(gid) if e["event_type"] == "revised"]
        assert len(events) == 1
        assert "new evidence" in events[0]["notes"]

    def test_revise_unknown_goal_safe(self):
        gm = _fresh()
        gm.revise("ghost", impact=1.0)


class TestPickNext:
    def test_empty_queue_returns_none(self):
        gm = _fresh()
        assert gm.pick_next() is None

    def test_returns_highest_priority(self):
        gm = _fresh()
        low = gm.propose("low", impact=0.2, confidence=0.2)
        high = gm.propose("high", impact=0.9, confidence=0.9)
        picked = gm.pick_next()
        assert picked["id"] == high
        # And it should now be active
        assert gm.get(high)["state"] == "active"
        # low is still proposed
        assert gm.get(low)["state"] == "proposed"

    def test_terminal_goals_skipped(self):
        gm = _fresh()
        done = gm.propose("done", impact=1.0)
        gm.complete(done)
        pending = gm.propose("pending", impact=0.1)
        picked = gm.pick_next()
        assert picked["id"] == pending

    def test_tiebreak_by_creation_order(self):
        gm = _fresh()
        a = gm.propose("a", impact=0.5, urgency=0.5, confidence=0.5, cost=0.5)
        time.sleep(0.001)
        b = gm.propose("b", impact=0.5, urgency=0.5, confidence=0.5, cost=0.5)
        picked = gm.pick_next()
        # Same priority → earlier creation wins
        assert picked["id"] == a


class TestListing:
    def test_list_by_state(self):
        gm = _fresh()
        a = gm.propose("a")
        b = gm.propose("b")
        gm.activate(b)
        proposed = gm.list_goals(state="proposed")
        active = gm.list_goals(state="active")
        assert [g["id"] for g in proposed] == [a]
        assert [g["id"] for g in active] == [b]

    def test_active_returns_all_live_states(self):
        gm = _fresh()
        gm.propose("proposed")
        b = gm.propose("active"); gm.activate(b)
        c = gm.propose("in_prog"); gm.activate(c); gm.start(c)
        d = gm.propose("done"); gm.complete(d)
        live = gm.active()
        assert len(live) == 3
        # Terminal goal excluded
        assert all(g["state"] != "completed" for g in live)

    def test_list_all(self):
        gm = _fresh()
        gm.propose("a")
        gm.propose("b")
        gm.propose("c")
        assert len(gm.list_goals()) == 3

    def test_children_of_parent(self):
        gm = _fresh()
        parent = gm.propose("parent")
        c1 = gm.propose("c1", parent_id=parent)
        c2 = gm.propose("c2", parent_id=parent)
        orphan = gm.propose("orphan")
        children = gm.children(parent)
        ids = {c["id"] for c in children}
        assert ids == {c1, c2}
        assert orphan not in ids


class TestStats:
    def test_stats_groups_by_state(self):
        gm = _fresh()
        gm.propose("a")
        b = gm.propose("b"); gm.activate(b)
        c = gm.propose("c"); gm.complete(c)
        d = gm.propose("d"); gm.fail(d)
        stats = gm.stats()
        assert stats["total"] == 4
        assert stats["by_state"]["proposed"] == 1
        assert stats["by_state"]["active"] == 1
        assert stats["by_state"]["completed"] == 1
        assert stats["by_state"]["failed"] == 1
        assert stats["active_count"] == 2  # proposed + active
        assert stats["terminal_count"] == 2  # completed + failed


class TestProposeFromSelfModel:
    def _fake_self_model(self, *, weaknesses=None, gaps=None):
        w_list = list(weaknesses or [])
        g_list = list(gaps or [])

        class Fake:
            def weaknesses(self, top_n=5):
                return w_list[:top_n]

            def knowledge_gaps(self, top_n=5):
                return g_list[:top_n]

        return Fake()

    def test_generates_practice_goals_for_weaknesses(self):
        gm = _fresh()
        sm = self._fake_self_model(weaknesses=[
            {"name": "engine.alpha", "score": 0.2, "confidence": 0.8},
            {"name": "engine.beta",  "score": 0.15, "confidence": 0.7},
        ])
        ids = gm.propose_from_self_model(sm)
        assert len(ids) == 2
        goals = [gm.get(i) for i in ids]
        assert all(g["source"].startswith("self_model.weakness:") for g in goals)
        assert any("engine.alpha" in g["source"] for g in goals)

    def test_generates_explore_goals_for_gaps(self):
        gm = _fresh()
        sm = self._fake_self_model(gaps=[
            {"name": "knowledge.marketing", "evidence_count": 1},
        ])
        ids = gm.propose_from_self_model(sm)
        assert len(ids) == 1
        g = gm.get(ids[0])
        assert "self_model.gap:" in g["source"]
        assert "explore" in g["what"].lower()

    def test_dedup_skips_already_active(self):
        gm = _fresh()
        sm = self._fake_self_model(weaknesses=[
            {"name": "engine.alpha", "score": 0.2, "confidence": 0.8},
        ])
        first = gm.propose_from_self_model(sm)
        second = gm.propose_from_self_model(sm)
        assert len(first) == 1
        assert len(second) == 0

    def test_dedup_allows_recreation_after_completion(self):
        gm = _fresh()
        sm = self._fake_self_model(weaknesses=[
            {"name": "engine.alpha", "score": 0.2, "confidence": 0.8},
        ])
        first = gm.propose_from_self_model(sm)
        gm.complete(first[0])
        # Now that it's completed, a new proposal is allowed
        second = gm.propose_from_self_model(sm)
        assert len(second) == 1

    def test_none_self_model_returns_empty(self):
        gm = _fresh()
        assert gm.propose_from_self_model(None) == []

    def test_broken_self_model_does_not_crash(self):
        gm = _fresh()

        class Broken:
            def weaknesses(self, top_n=5):
                raise RuntimeError("db down")

            def knowledge_gaps(self, top_n=5):
                raise RuntimeError("db down")

        assert gm.propose_from_self_model(Broken()) == []

    def test_max_limits_respected(self):
        gm = _fresh()
        many_weak = [
            {"name": f"engine.w{i}", "score": 0.1, "confidence": 0.9}
            for i in range(10)
        ]
        sm = self._fake_self_model(weaknesses=many_weak)
        ids = gm.propose_from_self_model(sm, max_from_weaknesses=3)
        assert len(ids) == 3


class TestEndToEndIntegration:
    """Cognitive integration: SelfModel → GoalManager → back to SelfModel."""

    def test_cycle_produces_goals_that_become_completed(self):
        from core.cognitive.self_model import SelfModel
        sm = SelfModel(db_path=tempfile.mktemp(suffix=".db"))
        gm = _fresh()

        # Simulate a store with one flaky engine
        for _ in range(15):
            sm.assess("engine.flaky", 0.2, source="cycle")
        # Now a confident weakness should surface
        weaknesses = sm.weaknesses()
        assert len(weaknesses) == 1

        # GoalManager picks up the weakness
        ids = gm.propose_from_self_model(sm)
        assert len(ids) == 1

        # Work the goal through its lifecycle
        picked = gm.pick_next()
        assert picked is not None
        assert picked["state"] == "active"
        gm.start(picked["id"])
        gm.update_progress(picked["id"], 0.5)
        gm.complete(picked["id"], result_notes="retrained engine")

        # Stats reflect one completed goal
        stats = gm.stats()
        assert stats["by_state"]["completed"] == 1
        assert stats["active_count"] == 0


class TestSingleton:
    def test_get_goal_manager_cached(self):
        from core.cognitive import goals as mod
        mod._instance = None
        a = mod.get_goal_manager()
        b = mod.get_goal_manager()
        assert a is b


# ── Defensive: _transition extra-column whitelist ────────────


class TestTransitionExtraWhitelist:
    def test_disallowed_column_is_dropped_silently(self):
        gm = _fresh()
        gid = gm.propose("X", urgency=0.5)
        # Pass a malicious key — must not be interpolated into SQL
        # and must not raise. The goal still transitions.
        gm._transition(
            gid, "active",
            extra={"progress; DROP TABLE goals; --": "evil"},
        )
        goal = gm.get(gid)
        assert goal["state"] == "active"
        # Table still exists and queryable.
        assert gm.get(gid) is not None

    def test_allowed_column_still_writes(self):
        gm = _fresh()
        gid = gm.propose("X", urgency=0.5)
        gm._transition(gid, "completed", extra={"progress": 1.0})
        goal = gm.get(gid)
        assert goal["state"] == "completed"
        assert goal["progress"] == pytest.approx(1.0)

    def test_complete_via_public_api_still_works(self):
        # Regression: complete() passes a known-safe extra dict; the
        # whitelist must accept progress + completed_at + result_notes.
        gm = _fresh()
        gid = gm.propose("X", urgency=0.5)
        gm.complete(gid, result_notes="done")
        assert gm.get(gid)["state"] == "completed"
        assert gm.get(gid)["progress"] == pytest.approx(1.0)


# ── Cross-source dedup (SelfModel ↔ Reflection) ──────────────


class TestActiveGoalTargetsDedup:
    def test_recognises_reflection_weakness_prefix(self):
        gm = _fresh()
        gm.propose(
            "Improve foo",
            source="reflection.weakness:engine.foo",
            urgency=0.5,
        )
        targets = gm._active_goal_targets()
        assert "practice:engine.foo" in targets

    def test_recognises_reflection_pattern_prefix(self):
        gm = _fresh()
        gm.propose(
            "Investigate bar",
            source="reflection.pattern:bar",
            urgency=0.5,
        )
        assert "explore:bar" in gm._active_goal_targets()

    def test_self_model_and_reflection_dedupe_each_other(self):
        # If Reflection already created a goal for engine.x,
        # propose_from_self_model must not create a duplicate.
        gm = _fresh()
        gm.propose(
            "Improve engine.x",
            source="reflection.weakness:engine.x",
            urgency=0.5,
        )

        class _SM:
            def weaknesses(self, top_n):
                return [{"name": "engine.x", "score": 0.2, "confidence": 0.9}]
            def knowledge_gaps(self, top_n):
                return []

        created = gm.propose_from_self_model(_SM())
        assert created == []  # blocked by Reflection's pre-existing goal

    def test_unknown_prefix_is_ignored(self):
        gm = _fresh()
        gm.propose("Random", source="custom.thing:x", urgency=0.5)
        # Not in the whitelist → not in dedup keys
        targets = gm._active_goal_targets()
        assert not any(t.endswith(":x") for t in targets)
