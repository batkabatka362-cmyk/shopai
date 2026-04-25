"""Knowledge transfer prioritizer tests."""
from __future__ import annotations

import unittest

from core.brain import knowledge_transfer_prioritizer as ktp


class TestValidate(unittest.TestCase):
    def test_bad_score_raises(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        bad = ktp.TransferCandidate(
            id="x", subject="r",
            source_store="a", target_store="b",
            evidence_strength=2.0,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        with self.assertRaises(ValueError):
            p.rank([bad])

    def test_blank_subject_raises(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        bad = ktp.TransferCandidate(
            id="x", subject="",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        with self.assertRaises(ValueError):
            p.rank([bad])


class TestRank(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ktp.KnowledgeTransferPrioritizer()

    def _c(self, **kw):
        defaults = dict(
            id="x", subject="rule",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
            source_trust=0.5,
        )
        defaults.update(kw)
        return ktp.TransferCandidate(**defaults)

    def test_ranks_by_score(self) -> None:
        low = self._c(id="low", expected_lift=0.1)
        high = self._c(id="high", expected_lift=0.9)
        ranked = self.p.rank([low, high])
        self.assertEqual(ranked[0].candidate.id, "high")

    def test_min_score_filter(self) -> None:
        low = self._c(
            id="low",
            expected_lift=0.01,
            evidence_strength=0.01,
            portability=0.01,
            novelty_to_peer=0.01,
            source_trust=0.01,
        )
        ranked = self.p.rank([low], min_score=0.5)
        self.assertEqual(ranked, [])

    def test_top_k(self) -> None:
        cands = [
            self._c(id=f"c{i}", expected_lift=i / 10)
            for i in range(5)
        ]
        ranked = self.p.rank(cands, top_k=2)
        self.assertEqual(len(ranked), 2)

    def test_reason_includes_drivers(self) -> None:
        c = self._c(expected_lift=1.0)
        ranked = self.p.rank([c])
        self.assertIn("lift", ranked[0].reason)


class TestWeights(unittest.TestCase):
    def test_weight_change_swaps_winner(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()

        def cand(name, **kw):
            defaults = dict(
                id=name, subject="r",
                source_store="a", target_store="b",
                evidence_strength=0.5,
                portability=0.5,
                novelty_to_peer=0.5,
                expected_lift=0.5,
                source_trust=0.5,
            )
            defaults.update(kw)
            return ktp.TransferCandidate(**defaults)

        # C1 wins on novelty; C2 wins on lift.
        c1 = cand("novelty_king", novelty_to_peer=1.0,
                  expected_lift=0.0)
        c2 = cand("lift_king", novelty_to_peer=0.0,
                  expected_lift=1.0)

        # Default weights favour lift (0.25 vs novelty 0.15)
        ranked_default = p.rank([c1, c2])
        self.assertEqual(
            ranked_default[0].candidate.id, "lift_king",
        )

        # Override weights to favour novelty
        p.set_weights(ktp.TransferWeights(
            evidence=0.1, portability=0.1,
            novelty=0.6, lift=0.1, trust=0.1,
        ))
        ranked_novel = p.rank([c1, c2])
        self.assertEqual(
            ranked_novel[0].candidate.id, "novelty_king",
        )


class TestQueries(unittest.TestCase):
    def test_recent(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        c = ktp.TransferCandidate(
            id="x", subject="r",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        p.rank([c])
        self.assertEqual(len(p.recent()), 1)

    def test_stats(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        s = p.stats()
        self.assertIn("weights", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        c = ktp.TransferCandidate(
            id="x", subject="r",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        p.rank([c])
        self.assertEqual(p.reset(), 1)


class TestDict(unittest.TestCase):
    def test_candidate_serialises(self) -> None:
        c = ktp.TransferCandidate(
            id="x", subject="r",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        d = c.as_dict()
        self.assertEqual(d["id"], "x")

    def test_ranked_serialises(self) -> None:
        p = ktp.KnowledgeTransferPrioritizer()
        c = ktp.TransferCandidate(
            id="x", subject="r",
            source_store="a", target_store="b",
            evidence_strength=0.5,
            portability=0.5,
            novelty_to_peer=0.5,
            expected_lift=0.5,
        )
        d = p.rank([c])[0].as_dict()
        self.assertIn("candidate", d)


if __name__ == "__main__":
    unittest.main()
