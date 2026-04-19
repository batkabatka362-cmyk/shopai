"""Voting ensemble tests."""
from __future__ import annotations

import unittest

from core.brain import voting_ensemble as ve


class TestRegistration(unittest.TestCase):
    def test_register_and_list(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill")
        e.register("b", lambda ctx: "kill")
        self.assertEqual(e.voters(), ["a", "b"])

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            ve.VotingEnsemble().register("", lambda ctx: "x")

    def test_zero_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            ve.VotingEnsemble().register(
                "a", lambda ctx: "x", weight=0,
            )

    def test_deregister(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "x")
        self.assertTrue(e.deregister("a"))
        self.assertFalse(e.deregister("a"))


class TestPlurality(unittest.TestCase):
    def test_majority_wins(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill")
        e.register("b", lambda ctx: "kill")
        e.register("c", lambda ctx: "scale")
        v = e.vote({}, scheme="plurality")
        self.assertEqual(v.winner, "kill")

    def test_unanimous_flag_set(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill")
        e.register("b", lambda ctx: "kill")
        v = e.vote({}, scheme="plurality")
        self.assertTrue(v.unanimous)

    def test_tie_broken_by_weight_then_name(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill", weight=1.0)
        e.register("b", lambda ctx: "scale", weight=2.0)
        v = e.vote({}, scheme="plurality")
        # Counts tied at 1 each; weight breaks → scale wins
        self.assertEqual(v.winner, "scale")


class TestWeighted(unittest.TestCase):
    def test_high_weight_voter_dominates(self) -> None:
        e = ve.VotingEnsemble()
        e.register("expert", lambda ctx: "scale", weight=10)
        e.register("novice", lambda ctx: "kill", weight=1)
        v = e.vote({}, scheme="weighted")
        self.assertEqual(v.winner, "scale")

    def test_confidence_affects_weight(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: {
            "choice": "kill", "confidence": 1.0,
        })
        e.register("b", lambda ctx: {
            "choice": "scale", "confidence": 0.1,
        })
        v = e.vote({}, scheme="weighted")
        self.assertEqual(v.winner, "kill")

    def test_disagreement_lowers_confidence(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill")
        e.register("b", lambda ctx: "scale")
        v = e.vote({}, scheme="weighted")
        self.assertLess(v.confidence, 1.0)


class TestUnanimous(unittest.TestCase):
    def test_all_agree_returns_winner(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "hold")
        e.register("b", lambda ctx: "hold")
        v = e.vote({}, scheme="unanimous")
        self.assertEqual(v.winner, "hold")
        self.assertTrue(v.unanimous)

    def test_disagreement_abstains(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "hold")
        e.register("b", lambda ctx: "kill")
        v = e.vote({}, scheme="unanimous")
        self.assertIsNone(v.winner)
        self.assertFalse(v.unanimous)

    def test_missing_ballot_abstains(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "hold")
        e.register("b", lambda ctx: None)   # abstain
        v = e.vote({}, scheme="unanimous")
        self.assertIsNone(v.winner)


class TestBorda(unittest.TestCase):
    def test_ranked_voting_picks_overall_best(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: {
            "ranking": ["scale", "hold", "kill"],
        })
        e.register("b", lambda ctx: {
            "ranking": ["scale", "kill", "hold"],
        })
        e.register("c", lambda ctx: {
            "ranking": ["kill", "scale", "hold"],
        })
        v = e.vote({}, scheme="borda_count")
        self.assertEqual(v.winner, "scale")

    def test_falls_back_on_plain_choice(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: {"choice": "kill"})
        e.register("b", lambda ctx: {"choice": "kill"})
        v = e.vote({}, scheme="borda_count")
        self.assertEqual(v.winner, "kill")


class TestErrors(unittest.TestCase):
    def test_unknown_scheme_raises(self) -> None:
        e = ve.VotingEnsemble()
        with self.assertRaises(ValueError):
            e.vote({}, scheme="bogus")

    def test_no_voters_abstains(self) -> None:
        v = ve.VotingEnsemble().vote({}, scheme="weighted")
        self.assertIsNone(v.winner)

    def test_broken_voter_skipped(self) -> None:
        e = ve.VotingEnsemble()
        def broken(ctx):
            raise RuntimeError("nope")
        e.register("broken", broken)
        e.register("ok", lambda ctx: "hold")
        v = e.vote({}, scheme="plurality")
        self.assertEqual(v.winner, "hold")


class TestMargin(unittest.TestCase):
    def test_margin_between_1st_and_2nd(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "kill")
        e.register("b", lambda ctx: "kill")
        e.register("c", lambda ctx: "hold")
        v = e.vote({}, scheme="plurality")
        self.assertEqual(ve.verdict_margin(v), 1.0)

    def test_single_candidate_zero_margin(self) -> None:
        e = ve.VotingEnsemble()
        e.register("a", lambda ctx: "only")
        v = e.vote({}, scheme="plurality")
        self.assertEqual(ve.verdict_margin(v), 0.0)


if __name__ == "__main__":
    unittest.main()
