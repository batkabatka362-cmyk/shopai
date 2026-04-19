"""Brain facade tests."""
from __future__ import annotations

import unittest

from core.brain import brain_facade as bf


class TestSingleton(unittest.TestCase):
    def test_brain_returns_same_instance(self) -> None:
        self.assertIs(bf.brain(), bf.brain())


class TestThink(unittest.TestCase):
    def test_think_returns_cycle_report_dict(self) -> None:
        r = bf.brain().think({"kind": "event", "niche": "audio"})
        self.assertIsInstance(r, dict)
        self.assertIn("stages", r)
        self.assertIn("observation", r)

    def test_think_preserves_last_cycle(self) -> None:
        b = bf.brain()
        b.think({"kind": "e1"})
        first_ref = b._last_cycle_report
        b.think({"kind": "e2"})
        # Reference should have advanced to the newer report
        self.assertIsNot(first_ref, b._last_cycle_report)


class TestLearn(unittest.TestCase):
    def test_learn_returns_dispatch_report(self) -> None:
        r = bf.brain().learn(
            kind="order",
            features={"niche": "audio"},
            source="shopify_api",
            sign=1.0,
            success=True,
            value=100.0,
            kpi="revenue",
            action="scale",
        )
        self.assertIn("delivered", r)

    def test_learn_empty_features_still_fires(self) -> None:
        r = bf.brain().learn(kind="order")
        self.assertIsInstance(r, dict)


class TestIntrospect(unittest.TestCase):
    def test_introspect_returns_snapshot(self) -> None:
        snap = bf.brain().introspect()
        self.assertGreater(snap.ts, 0)
        d = snap.as_dict()
        for key in (
            "world_model", "epistemic", "hypothesis", "reward",
            "policies", "habits", "trust", "self_improvement",
            "surprise", "regret",
            "commitments", "learning",
        ):
            self.assertIn(key, d)


class TestCommit(unittest.TestCase):
    def test_commit_returns_id(self) -> None:
        cid = bf.brain().commit(
            promise="ship v21", owner="claude",
            due_at=9_999_999_999.0,
        )
        self.assertIsNotNone(cid)
        self.assertIsInstance(cid, str)

    def test_commit_bad_input_returns_none(self) -> None:
        cid = bf.brain().commit(promise="", owner="", due_at=0)
        self.assertIsNone(cid)

    def test_commitments_reflected_in_snapshot(self) -> None:
        b = bf.brain()
        b.commit(
            promise="ship v21 regression",
            owner="claude",
            due_at=9_999_999_999.0,
        )
        snap = b.introspect()
        self.assertGreaterEqual(snap.commitments.get("pending", 0), 1)


class TestEvidence(unittest.TestCase):
    def test_empty_evidence_abstains(self) -> None:
        r = bf.brain().evidence_ready([])
        self.assertEqual(r["verdict"], "abstain")

    def test_strong_evidence_decides(self) -> None:
        import time
        now = time.time()
        r = bf.brain().evidence_ready(
            [
                {"source": "shopify", "weight": 0.9, "ts": now},
                {"source": "autods",  "weight": 0.85, "ts": now},
                {"source": "meta",    "weight": 0.8, "ts": now},
            ],
            min_sources=2,
        )
        self.assertEqual(r["verdict"], "decide")


class TestTrack(unittest.TestCase):
    def test_track_swallows_errors(self) -> None:
        # Shouldn't raise even with odd inputs.
        bf.brain().track("nowhere", "nothing", float("nan"))


class TestValidateClaims(unittest.TestCase):
    def test_conflicting_claims_flagged(self) -> None:
        from core.memory.knowledge_validator import Claim
        r = bf.brain().validate_claims([
            Claim("p1", "price", 20, "a", 0.9),
            Claim("p1", "price", 30, "b", 0.6),
        ])
        self.assertGreaterEqual(len(r["conflicts"]), 1)

    def test_agreement_no_conflicts(self) -> None:
        from core.memory.knowledge_validator import Claim
        r = bf.brain().validate_claims([
            Claim("p1", "name", "Blue", "a", 0.9),
            Claim("p1", "name", "Blue", "b", 0.7),
        ])
        self.assertEqual(len(r["conflicts"]), 0)


class TestExplain(unittest.TestCase):
    def test_explain_without_prior_decision(self) -> None:
        bf._BRAIN = bf.BrainFacade()
        r = bf._BRAIN.explain()
        self.assertIn("summary", r)

    def test_explain_after_think_uses_context(self) -> None:
        bf._BRAIN = bf.BrainFacade()
        b = bf._BRAIN
        b.think({"kind": "order", "niche": "audio"})
        r = b.explain()
        self.assertIn("decision_id", r)


class TestHousekeep(unittest.TestCase):
    def test_housekeep_returns_dict(self) -> None:
        r = bf.brain().housekeep()
        self.assertIsInstance(r, dict)
        # Could be a real report or failure envelope; both carry
        # a recognisable shape.
        self.assertTrue(
            "tables" in r or "status" in r,
        )


if __name__ == "__main__":
    unittest.main()
