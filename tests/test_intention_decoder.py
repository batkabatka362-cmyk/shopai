"""Intention decoder tests."""
from __future__ import annotations

import unittest

from core.brain import intention_decoder as id_


class TestDecodeEmpty(unittest.TestCase):
    def test_empty_string_empty_tree(self) -> None:
        tree = id_.decode("")
        self.assertEqual(tree.sub_intents, [])
        self.assertFalse(tree.ambiguous)

    def test_whitespace_only_empty(self) -> None:
        self.assertEqual(id_.decode("   ").sub_intents, [])


class TestSingleIntent(unittest.TestCase):
    def test_kill_intent_extracted(self) -> None:
        tree = id_.decode("kill audio ads")
        self.assertEqual(len(tree.sub_intents), 1)
        si = tree.sub_intents[0]
        self.assertEqual(si.intent, "kill")
        self.assertEqual(si.slots.get("niche"), "audio")
        self.assertIn("audio", si.targets)

    def test_confidence_higher_with_slots(self) -> None:
        tree_with = id_.decode("kill audio ads $20")
        tree_without = id_.decode("kill it")
        self.assertGreater(
            tree_with.sub_intents[0].confidence,
            tree_without.sub_intents[0].confidence,
        )


class TestMultipleIntents(unittest.TestCase):
    def test_comma_also_splits(self) -> None:
        tree = id_.decode(
            "kill bad audio ads, also scale the winner",
        )
        self.assertEqual(len(tree.sub_intents), 2)
        intents = [si.intent for si in tree.sub_intents]
        self.assertIn("kill", intents)
        self.assertIn("scale", intents)

    def test_then_splits(self) -> None:
        tree = id_.decode("sync product then publish it")
        intents = [si.intent for si in tree.sub_intents]
        self.assertEqual(len(tree.sub_intents), 2)
        self.assertIn("sync", intents)
        self.assertIn("publish", intents)

    def test_semicolon_splits(self) -> None:
        tree = id_.decode("kill audio; scale fashion")
        self.assertEqual(len(tree.sub_intents), 2)

    def test_mongolian_bas_splits(self) -> None:
        tree = id_.decode("kill audio bas scale fashion")
        self.assertEqual(len(tree.sub_intents), 2)


class TestAmbiguity(unittest.TestCase):
    def test_distinct_high_conf_intents_flagged(self) -> None:
        tree = id_.decode(
            "kill bad audio ads, also scale the winner",
        )
        self.assertTrue(tree.ambiguous)

    def test_single_clear_intent_not_ambiguous(self) -> None:
        tree = id_.decode("kill audio ads $20")
        self.assertFalse(tree.ambiguous)

    def test_unknown_intent_ambiguous(self) -> None:
        tree = id_.decode("la la la")
        self.assertTrue(tree.ambiguous)

    def test_pronoun_lowers_confidence(self) -> None:
        with_pronoun = id_.decode("kill it")
        without_pronoun = id_.decode("kill audio ads")
        self.assertLess(
            with_pronoun.sub_intents[0].confidence,
            without_pronoun.sub_intents[0].confidence,
        )


class TestTargets(unittest.TestCase):
    def test_sku_hint_captured(self) -> None:
        tree = id_.decode("kill SKU-123")
        self.assertTrue(tree.sub_intents[0].targets)

    def test_hero_captured(self) -> None:
        tree = id_.decode("scale the hero product")
        self.assertIn("hero", tree.sub_intents[0].targets)


class TestBestIntent(unittest.TestCase):
    def test_best_picks_highest_confidence(self) -> None:
        tree = id_.decode(
            "maybe something, also kill audio ads $20",
        )
        best = tree.best_intent
        self.assertEqual(best.intent, "kill")

    def test_best_none_for_empty(self) -> None:
        self.assertIsNone(id_.decode("").best_intent)


class TestDecodeMany(unittest.TestCase):
    def test_batch_preserves_order(self) -> None:
        trees = id_.decode_many([
            "kill audio ads",
            "scale winner",
        ])
        self.assertEqual(
            [t.sub_intents[0].intent for t in trees],
            ["kill", "scale"],
        )

    def test_batch_non_string_coerced(self) -> None:
        # Values that aren't strings shouldn't crash the batch
        trees = id_.decode_many([None, 123, "kill audio"])  # type: ignore[list-item]
        self.assertEqual(len(trees), 3)


class TestDict(unittest.TestCase):
    def test_tree_serialises(self) -> None:
        d = id_.decode("kill audio ads").as_dict()
        self.assertIn("sub_intents", d)
        self.assertIn("best", d)

    def test_sub_intent_serialises(self) -> None:
        si = id_.SubIntent(
            intent="kill", targets=["audio"],
            slots={"amount_usd": 20.0},
            confidence=0.9, raw="kill audio $20",
        )
        self.assertEqual(si.as_dict()["intent"], "kill")


if __name__ == "__main__":
    unittest.main()
