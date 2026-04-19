"""Proposal arbiter tests."""
from __future__ import annotations

import unittest

from core.brain import proposal_arbiter as pa


class TestArbitrate(unittest.TestCase):
    def setUp(self) -> None:
        self.arb = pa.ProposalArbiter()

    def test_blank_target_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.arb.arbitrate("", [])

    def test_no_proposals_rejects(self) -> None:
        out = self.arb.arbitrate("kill_at_roas", [])
        self.assertEqual(out.verdict, "reject_all")
        self.assertEqual(out.winner_id, "")

    def test_all_low_evidence_rejects(self) -> None:
        p1 = pa.Proposal(
            id="p1", target="t", new_value=1.3,
            evidence_score=0.1, ts=100.0,
        )
        p2 = pa.Proposal(
            id="p2", target="t", new_value=1.4,
            evidence_score=0.15, ts=200.0,
        )
        out = self.arb.arbitrate(
            "t", [p1, p2], current_value=1.5,
        )
        self.assertEqual(out.verdict, "reject_all")

    def test_single_good_proposal_accepted(self) -> None:
        p = pa.Proposal(
            id="p1", target="t", new_value=1.4,
            evidence_score=0.8, ts=100.0,
        )
        out = self.arb.arbitrate(
            "t", [p], current_value=1.5,
        )
        self.assertEqual(out.verdict, "accept")
        self.assertEqual(out.winner_id, "p1")

    def test_tight_margin_defers(self) -> None:
        p1 = pa.Proposal(
            id="p1", target="t", new_value=1.3,
            evidence_score=0.7, ts=100.0,
        )
        p2 = pa.Proposal(
            id="p2", target="t", new_value=1.4,
            evidence_score=0.71, ts=100.0,
        )
        out = self.arb.arbitrate(
            "t", [p1, p2], current_value=1.5,
        )
        # Identical recency and similar scores → defer
        self.assertEqual(out.verdict, "defer")

    def test_higher_evidence_wins(self) -> None:
        p1 = pa.Proposal(
            id="p1", target="t", new_value=1.3,
            evidence_score=0.4, ts=100.0,
        )
        p2 = pa.Proposal(
            id="p2", target="t", new_value=1.4,
            evidence_score=0.9, ts=100.0,
        )
        out = self.arb.arbitrate(
            "t", [p1, p2], current_value=1.5,
        )
        self.assertEqual(out.winner_id, "p2")

    def test_conservatism_breaks_tie(self) -> None:
        # Same evidence, same time; prefer smaller delta
        p1 = pa.Proposal(
            id="p1", target="t", new_value=1.0,
            evidence_score=0.8, ts=100.0,
        )
        p2 = pa.Proposal(
            id="p2", target="t", new_value=1.4,
            evidence_score=0.8, ts=100.0,
        )
        # current=1.5; p2 delta=0.1, p1 delta=0.5; p2 wins by cons.
        out = self.arb.arbitrate(
            "t", [p1, p2], current_value=1.5,
        )
        self.assertEqual(out.winner_id, "p2")

    def test_mismatched_targets_ignored(self) -> None:
        p1 = pa.Proposal(
            id="p1", target="other", new_value=1.0,
            evidence_score=0.9,
        )
        out = self.arb.arbitrate("t", [p1])
        self.assertEqual(out.verdict, "reject_all")


class TestReputation(unittest.TestCase):
    def setUp(self) -> None:
        self.arb = pa.ProposalArbiter()

    def test_blank_proposer_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.arb.set_reputation("", 0.5)

    def test_bad_score_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.arb.set_reputation("owner", 1.5)

    def test_default_half(self) -> None:
        self.assertEqual(self.arb.reputation("nobody"), 0.5)

    def test_set_and_use(self) -> None:
        self.arb.set_reputation("owner", 1.0)
        self.arb.set_reputation("rando", 0.0)
        # Equal everything else, reputation breaks tie
        p1 = pa.Proposal(
            id="p1", target="t", new_value=1.4,
            evidence_score=0.8, proposer="rando", ts=100.0,
        )
        p2 = pa.Proposal(
            id="p2", target="t", new_value=1.4,
            evidence_score=0.8, proposer="owner", ts=100.0,
        )
        out = self.arb.arbitrate(
            "t", [p1, p2], current_value=1.5,
        )
        self.assertEqual(out.winner_id, "p2")


class TestNonNumeric(unittest.TestCase):
    def test_non_numeric_neutral(self) -> None:
        arb = pa.ProposalArbiter()
        p = pa.Proposal(
            id="p", target="t",
            new_value={"policy": "b"},
            evidence_score=0.8, ts=100.0,
        )
        out = arb.arbitrate(
            "t", [p], current_value={"policy": "a"},
        )
        # Should not crash, should accept (single high-evidence)
        self.assertEqual(out.verdict, "accept")


class TestQueries(unittest.TestCase):
    def test_recent(self) -> None:
        arb = pa.ProposalArbiter()
        for i in range(3):
            arb.arbitrate(f"t{i}", [])
        r = arb.recent(limit=2)
        self.assertEqual(len(r), 2)

    def test_stats(self) -> None:
        arb = pa.ProposalArbiter()
        arb.arbitrate("t", [])
        s = arb.stats()
        self.assertEqual(s["arbitrations"], 1)
        self.assertEqual(s["by_verdict"]["reject_all"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        arb = pa.ProposalArbiter()
        arb.arbitrate("t", [])
        self.assertEqual(arb.reset(), 1)


class TestDict(unittest.TestCase):
    def test_proposal_serialises(self) -> None:
        p = pa.Proposal(
            id="p", target="t", new_value=1,
            evidence_score=0.8,
        )
        d = p.as_dict()
        self.assertEqual(d["id"], "p")

    def test_outcome_serialises(self) -> None:
        arb = pa.ProposalArbiter()
        out = arb.arbitrate("t", [])
        d = out.as_dict()
        self.assertEqual(d["verdict"], "reject_all")


if __name__ == "__main__":
    unittest.main()
