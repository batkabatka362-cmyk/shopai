"""Skill transfer tests."""
from __future__ import annotations

import unittest

from core.brain import skill_transfer as st


class TestSkill(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            st.TransferableSkill(
                name="", learned_context={},
                original_win_rate=0.5,
            )

    def test_win_rate_out_of_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            st.TransferableSkill(
                name="x", learned_context={},
                original_win_rate=1.5,
            )

    def test_negative_uses_raises(self) -> None:
        with self.assertRaises(ValueError):
            st.TransferableSkill(
                name="x", learned_context={},
                original_win_rate=0.5, uses=-1,
            )


class TestSimilarity(unittest.TestCase):
    def test_identical_full(self) -> None:
        sim = st._trait_similarity({"niche": "audio"}, {"niche": "audio"})
        self.assertEqual(sim, 1.0)

    def test_disjoint_zero(self) -> None:
        sim = st._trait_similarity({"a": 1}, {"b": 2})
        self.assertEqual(sim, 0.0)

    def test_partial(self) -> None:
        sim = st._trait_similarity(
            {"niche": "audio", "country": "us"},
            {"niche": "audio", "country": "eu"},
        )
        # 1 shared (niche=audio), 2 distinct (country vals) → 1/3
        self.assertAlmostEqual(sim, 1 / 3)

    def test_empty_zero(self) -> None:
        self.assertEqual(st._trait_similarity({}, {"a": 1}), 0.0)


class TestConfig(unittest.TestCase):
    def test_invalid_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            st.SkillTransfer(floor_similarity=2.0)

    def test_inverted_thresholds_raise(self) -> None:
        with self.assertRaises(ValueError):
            st.SkillTransfer(
                moderate_threshold=0.7,
                strong_threshold=0.3,
            )


class TestRegister(unittest.TestCase):
    def test_duplicate_rejected(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="s", learned_context={},
            original_win_rate=0.5,
        ))
        with self.assertRaises(ValueError):
            t.register(st.TransferableSkill(
                name="s", learned_context={},
                original_win_rate=0.5,
            ))

    def test_overwrite_allowed(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="s", learned_context={},
            original_win_rate=0.5,
        ))
        t.register(
            st.TransferableSkill(
                name="s", learned_context={},
                original_win_rate=0.9,
            ),
            overwrite=True,
        )
        self.assertEqual(t.skills()[0].original_win_rate, 0.9)

    def test_unregister(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="s", learned_context={},
            original_win_rate=0.5,
        ))
        self.assertTrue(t.unregister("s"))
        self.assertFalse(t.unregister("s"))


class TestEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.t = st.SkillTransfer()
        self.t.register(st.TransferableSkill(
            name="kill_at_roas_1.5",
            learned_context={"niche": "audio", "currency": "USD"},
            original_win_rate=0.9,
        ))
        self.t.register(st.TransferableSkill(
            name="discount_monday",
            learned_context={"niche": "fashion"},
            original_win_rate=0.7,
        ))

    def test_matching_niche_strong(self) -> None:
        rec = self.t.evaluate({"niche": "audio", "currency": "USD"})
        self.assertEqual(
            rec[0].skill.name, "kill_at_roas_1.5",
        )
        self.assertEqual(rec[0].verdict, "strong")

    def test_unrelated_context_refuses(self) -> None:
        rec = self.t.evaluate({"language": "mongolian"})
        # Low similarity + not in target → refuse
        for r in rec:
            self.assertEqual(r.verdict, "refuse")

    def test_tag_filter(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="a", learned_context={"x": 1},
            original_win_rate=0.9, tags=("kill",),
        ))
        t.register(st.TransferableSkill(
            name="b", learned_context={"x": 1},
            original_win_rate=0.9, tags=("scale",),
        ))
        rec = t.evaluate({"x": 1}, tags=("kill",))
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].skill.name, "a")


class TestBest(unittest.TestCase):
    def test_best_returns_non_refused(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="a", learned_context={"niche": "audio"},
            original_win_rate=0.8,
        ))
        t.register(st.TransferableSkill(
            name="b", learned_context={"niche": "fashion"},
            original_win_rate=0.9,
        ))
        best = t.best({"niche": "audio"})
        self.assertEqual(best.skill.name, "a")

    def test_all_refused_returns_none(self) -> None:
        t = st.SkillTransfer(floor_similarity=0.99)
        t.register(st.TransferableSkill(
            name="a", learned_context={"niche": "audio"},
            original_win_rate=0.9,
        ))
        self.assertIsNone(t.best({"completely": "different"}))


class TestTransferFromFederator(unittest.TestCase):
    def test_empty_federator_empty_result(self) -> None:
        class FakeFed:
            def best_rules_for(self, store, top_n=10):
                return []

            def stores(self):
                return []

        self.assertEqual(
            st.transfer_from_federator(FakeFed(), "s"), [],
        )

    def test_federator_report_wrapped(self) -> None:
        class FakeReport:
            def __init__(self, rule_id, score):
                self.rule_id = rule_id
                self.federated_score = score
                self.contributors = [{"uses": 10}]

        class FakeStore:
            store_id = "target"
            traits = {"niche": "audio"}

        class FakeFed:
            def best_rules_for(self, store, top_n=10):
                return [
                    FakeReport("rule1", 0.8),
                    FakeReport("rule2", 0.2),
                ]

            def stores(self):
                return [FakeStore()]

        recs = st.transfer_from_federator(FakeFed(), "target")
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0].verdict, "strong")
        self.assertEqual(recs[1].verdict, "weak")


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="s", learned_context={},
            original_win_rate=0.5,
        ))
        s = t.stats()
        self.assertEqual(s["skills"], 1)
        self.assertIn("floor_similarity", s)


class TestDict(unittest.TestCase):
    def test_recommendation_serialises(self) -> None:
        t = st.SkillTransfer()
        t.register(st.TransferableSkill(
            name="s", learned_context={"x": 1},
            original_win_rate=0.8,
        ))
        rec = t.evaluate({"x": 1})[0]
        d = rec.as_dict()
        self.assertIn("skill", d)
        self.assertIn("verdict", d)


if __name__ == "__main__":
    unittest.main()
