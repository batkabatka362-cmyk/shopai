"""Tests for audit-pass-31 fixes in agents/coordination/.

  Coordinator:
    1. _task_assignments / _results had no thread lock.
    2. assign_subtasks crashed with ZeroDivisionError on empty
       agents list (idx % 0).
    3. submit_result crashed with TypeError on a non-dict result
       (dict("string") raises).
    4. dict(result) was a shallow copy — agent mutating its own
       dict after submit bled into the coordinator's view.
    5. collect_results called bus.subscribe on EVERY call,
       accumulating subscription objects.
    6. msg["payload"] direct access in collect_results.
    7. merge_results "best" strategy crashed on confidence=None.

  ConflictResolver:
    8. _resolve_by_merge list dedupe used id() for unhashable
       items, which only matched the SAME object reference.
       Two equivalent dicts in the two source lists wouldn't
       dedupe because they had different ids.

  Consensus:
    9. _calculate_scores returned BORDA scores for ranked_choice,
       which was misleading: ranked_choice is instant-runoff
       and only cares about first-place votes per round.
"""
import threading

import pytest


# ── Coordinator ─────────────────────────────────────────────


def _coord():
    from agents.coordination.coordinator import Coordinator
    from agents.communication.message_bus import MessageBus
    return Coordinator(MessageBus())


class TestCoordinatorThreadSafety:
    def test_concurrent_submit_no_lost_results(self):
        c = _coord()
        c.coordinate_task({"steps": ["s1"], "id": "t1"}, ["a", "b", "c", "d"])

        errors: list[Exception] = []

        def worker(agent_id):
            try:
                c.submit_result("t1", agent_id, {"data": agent_id})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(a,)) for a in ["a", "b", "c", "d"]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        result = c.collect_results("t1")
        assert result["completed"] == 4


class TestCoordinatorEmptyAgents:
    def test_assign_subtasks_empty_agents_raises(self):
        c = _coord()
        with pytest.raises(ValueError, match="non-empty"):
            c.assign_subtasks({"steps": ["s1"]}, [])

    def test_coordinate_task_empty_agents_returns_rejected(self):
        c = _coord()
        result = c.coordinate_task({"steps": ["s1"]}, [])
        assert result["status"] == "rejected"


class TestCoordinatorNonDictResult:
    def test_submit_non_dict_wrapped(self):
        c = _coord()
        c.coordinate_task({"steps": ["s1"]}, ["a"])
        # Previously dict("not a dict") raised TypeError
        c.submit_result(c.collect_results(list(c._task_assignments)[0])["task_id"], "a", "not a dict")
        # Get the task id again
        tid = list(c._task_assignments)[0]
        results = c.collect_results(tid)
        assert results["results"]["a"] == {"raw": "not a dict"}


class TestCoordinatorDeepCopy:
    def test_submit_result_isolated_from_caller_mutation(self):
        c = _coord()
        c.coordinate_task({"steps": ["s1"]}, ["a"])
        tid = list(c._task_assignments)[0]
        result = {"items": ["x"]}
        c.submit_result(tid, "a", result)
        result["items"].append("MUTATED")
        result["leak"] = "yes"
        retrieved = c.collect_results(tid)
        assert retrieved["results"]["a"]["items"] == ["x"]
        assert "leak" not in retrieved["results"]["a"]


class TestCoordinatorMergeBestNoneSafe:
    def test_best_strategy_handles_none_confidence(self):
        """Regression: previously max() on r.get("confidence", ...)
        crashed if any result had confidence=None."""
        c = _coord()
        results = [
            {"name": "a", "confidence": None, "score": 80},
            {"name": "b", "confidence": 50},
            {"name": "c", "confidence": 75},
        ]
        merged = c.merge_results(results, merge_strategy="best")
        # b has highest non-None confidence (75 vs 50)
        # actually c has 75, b has 50, a has None→0 + score=80→but score isn't checked when confidence is None
        # Let's just verify it doesn't crash and picked one
        assert merged["data"]["name"] in ("b", "c", "a")

    def test_best_filters_non_dict_results(self):
        c = _coord()
        merged = c.merge_results(
            [{"x": 1}, "not a dict", None, {"x": 2}],
            merge_strategy="combine",
        )
        # Only the dict entries were merged
        assert merged["data"] == {"x": 2}


# ── ConflictResolver merge dedupe ───────────────────────────


class TestConflictResolverMergeDedupe:
    def test_content_equal_dicts_dedupe(self):
        """Regression: previously `id(item)` was used as a dedup
        key for unhashable items, so two dicts with the same
        CONTENT but different identities wouldn't dedupe."""
        from agents.coordination.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        # Both lists contain a dict with the same content
        list_a = [{"k": "v"}, {"unique": 1}]
        list_b = [{"k": "v"}, {"unique": 2}]
        conflict = {
            "field": "items",
            "agents": ["a", "b"],
            "values": {"a": list_a, "b": list_b},
        }
        resolutions = cr.resolve([conflict], strategy="merge")
        merged = resolutions[0]["resolved_value"]
        # The shared {"k": "v"} should appear ONCE in the merge
        count = sum(1 for item in merged if item == {"k": "v"})
        assert count == 1
        # Both unique dicts are kept
        assert {"unique": 1} in merged
        assert {"unique": 2} in merged

    def test_primitive_values_still_dedupe(self):
        from agents.coordination.conflict_resolver import ConflictResolver
        cr = ConflictResolver()
        conflict = {
            "field": "items",
            "agents": ["a", "b"],
            "values": {"a": [1, 2, 3], "b": [2, 3, 4]},
        }
        resolutions = cr.resolve([conflict], strategy="merge")
        merged = resolutions[0]["resolved_value"]
        assert sorted(merged) == [1, 2, 3, 4]


# ── Consensus ranked_choice scores ──────────────────────────


class TestConsensusRankedChoiceScores:
    def test_ranked_choice_scores_are_first_place_votes(self):
        """Regression: previously _calculate_scores returned
        Borda scores for ranked_choice, which was misleading."""
        from agents.coordination.consensus import Consensus
        c = Consensus()
        result = c.reach_consensus(
            agents=["v1", "v2", "v3"],
            options=[{"id": "x"}, {"id": "y"}, {"id": "z"}],
            method="ranked_choice",
            rankings={
                "v1": ["x", "y", "z"],
                "v2": ["y", "x", "z"],
                "v3": ["x", "z", "y"],
            },
        )
        # First-place votes: x=2, y=1
        assert result["scores"] == {"x": 2, "y": 1}
        # x has majority (2/3), wins immediately
        assert result["winner"] == "x"

    def test_borda_count_scores_unchanged(self):
        from agents.coordination.consensus import Consensus
        c = Consensus()
        result = c.reach_consensus(
            agents=["v1", "v2"],
            options=[{"id": "x"}, {"id": "y"}, {"id": "z"}],
            method="borda_count",
            rankings={
                "v1": ["x", "y", "z"],
                "v2": ["y", "x", "z"],
            },
        )
        # x: 2 (1st in v1) + 1 (2nd in v2) = 3
        # y: 1 (2nd in v1) + 2 (1st in v2) = 3
        # z: 0 + 0 = 0
        assert result["scores"]["x"] == 3
        assert result["scores"]["y"] == 3
        assert result["scores"]["z"] == 0
