"""Deliberation loop tests."""
from __future__ import annotations

import unittest

from core.brain import deliberation_loop as dl


class TestTrivial(unittest.TestCase):
    def test_clean_proposal_commits_first_round(self) -> None:
        propose = lambda ctx, hist: {"action": "scale"}
        critique = lambda c, ctx: []
        trace = dl.deliberate("q1", {}, propose, critique)
        self.assertTrue(trace.converged)
        self.assertEqual(trace.winner, {"action": "scale"})
        self.assertEqual(len(trace.rounds), 1)

    def test_seed_used_on_first_round(self) -> None:
        propose = lambda ctx, hist: {"action": "fresh"}
        critique = lambda c, ctx: []
        trace = dl.deliberate(
            "q", {}, propose, critique,
            seed_candidate={"action": "seed"},
        )
        # Seed committed immediately — never hit propose()
        self.assertEqual(trace.winner["action"], "seed")


class TestRevision(unittest.TestCase):
    def test_blockers_trigger_revision(self) -> None:
        attempts = {"n": 0}

        def propose(ctx, hist):
            attempts["n"] += 1
            return {"action": f"v{attempts['n']}"}

        def critique(candidate, ctx):
            if candidate["action"] == "v1":
                return [{"severity": "high", "note": "bad path"}]
            return []

        trace = dl.deliberate("q", {}, propose, critique, max_rounds=3)
        self.assertEqual(trace.winner["action"], "v2")
        self.assertEqual(len(trace.rounds), 2)
        self.assertTrue(trace.rounds[0].revised)
        self.assertFalse(trace.rounds[1].revised)

    def test_low_severity_not_blocker(self) -> None:
        propose = lambda ctx, hist: {"action": "x"}
        critique = lambda c, ctx: [
            {"severity": "low", "note": "stylistic"},
        ]
        trace = dl.deliberate("q", {}, propose, critique)
        # Low-severity shouldn't force a revision
        self.assertEqual(trace.winner, {"action": "x"})
        self.assertEqual(len(trace.rounds), 1)


class TestBudget(unittest.TestCase):
    def test_budget_exhausted_picks_lowest_score(self) -> None:
        counter = {"n": 0}

        def propose(ctx, hist):
            counter["n"] += 1
            return {"action": f"attempt_{counter['n']}"}

        # Every candidate has SOME high-severity critique
        severities = {
            "attempt_1": "critical",
            "attempt_2": "high",
            "attempt_3": "high",
        }

        def critique(c, ctx):
            return [{"severity": severities.get(c["action"], "high")}]

        trace = dl.deliberate("q", {}, propose, critique, max_rounds=3)
        self.assertIsNotNone(trace.winner)
        self.assertIn("budget_exhausted", trace.commit_reason)
        # attempt_2 has score 2, attempt_1 has 3, attempt_3 has 2 — tie breaks first min
        self.assertIn(trace.winner["action"], ("attempt_2", "attempt_3"))

    def test_zero_budget_raises(self) -> None:
        with self.assertRaises(ValueError):
            dl.deliberate(
                "q", {}, lambda c, h: {}, lambda c, ctx: [],
                max_rounds=0,
            )

    def test_propose_returning_none_exits(self) -> None:
        trace = dl.deliberate(
            "q", {}, lambda c, h: None, lambda c, ctx: [],
        )
        self.assertEqual(trace.commit_reason, "no_candidate_produced")
        self.assertIsNone(trace.winner)


class TestConvergence(unittest.TestCase):
    def test_repeat_candidate_detected(self) -> None:
        propose = lambda ctx, hist: {"action": "only_one"}
        critique = lambda c, ctx: [{"severity": "high"}]
        trace = dl.deliberate(
            "q", {}, propose, critique, max_rounds=5,
        )
        self.assertIn("converged_on_repeat", trace.commit_reason)
        self.assertTrue(trace.converged)

    def test_propose_exception_exits(self) -> None:
        def bad(ctx, hist):
            raise RuntimeError("x")

        trace = dl.deliberate(
            "q", {}, bad, lambda c, ctx: [],
        )
        self.assertIn("propose_raised", trace.commit_reason)


class TestCritiqueExceptions(unittest.TestCase):
    def test_critique_raising_treated_as_critical(self) -> None:
        attempts = {"n": 0}

        def propose(ctx, hist):
            attempts["n"] += 1
            return {"action": f"v{attempts['n']}"}

        def boom(c, ctx):
            raise RuntimeError("critic down")

        trace = dl.deliberate(
            "q", {}, propose, boom, max_rounds=2,
        )
        # Still produced a trace even though critique failed
        self.assertEqual(len(trace.rounds), 2)
        # All rounds had critical critiques, so picked best
        self.assertIsNotNone(trace.winner)


class TestBlockerPropagation(unittest.TestCase):
    def test_blocker_passed_to_propose(self) -> None:
        seen_blockers: list[list[str]] = []

        def propose(ctx, hist):
            seen_blockers.append(list(ctx.get("blocked") or []))
            return {"action": f"try_{len(hist)}"}

        def critique(c, ctx):
            if c["action"] == "try_0":
                return [{"severity": "high", "note": "pattern_alpha"}]
            return []

        trace = dl.deliberate(
            "q", {}, propose, critique, max_rounds=3,
        )
        # Second propose should see 'pattern_alpha' as blocked
        self.assertEqual(seen_blockers[0], [])
        self.assertIn("pattern_alpha", seen_blockers[1])


class TestDict(unittest.TestCase):
    def test_trace_serialises(self) -> None:
        propose = lambda ctx, hist: {"action": "x"}
        critique = lambda c, ctx: []
        trace = dl.deliberate("q", {}, propose, critique)
        d = trace.as_dict()
        self.assertIn("winner", d)
        self.assertIn("rounds", d)
        self.assertIn("commit_reason", d)


class TestFingerprint(unittest.TestCase):
    def test_order_independent(self) -> None:
        a = dl._fingerprint({"x": 1, "y": 2})
        b = dl._fingerprint({"y": 2, "x": 1})
        self.assertEqual(a, b)

    def test_value_matters(self) -> None:
        a = dl._fingerprint({"x": 1})
        b = dl._fingerprint({"x": 2})
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
