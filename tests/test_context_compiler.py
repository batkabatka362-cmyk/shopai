"""Context compiler tests."""
from __future__ import annotations

import unittest

from core.brain import context_compiler as cc


class TestCanonicalise(unittest.TestCase):
    def test_lowercases_and_strips(self) -> None:
        ctx = cc.compile_context({"NICHE": "  Audio  "})
        self.assertEqual(ctx.features.get("niche"), "audio")

    def test_defaults_fill_missing(self) -> None:
        ctx = cc.compile_context({})
        self.assertEqual(ctx.raw["niche"], "unknown")
        self.assertEqual(ctx.raw["copy_tone"], "friendly")

    def test_coerces_open_launches(self) -> None:
        ctx = cc.compile_context({"open_launches": "3"})
        self.assertEqual(ctx.raw["open_launches"], 3)


class TestSignature(unittest.TestCase):
    def test_signature_stable_across_key_order(self) -> None:
        a = cc.compile_context({"niche": "audio",
                                  "copy_tone": "luxury"})
        b = cc.compile_context({"copy_tone": "luxury",
                                  "niche": "audio"})
        self.assertEqual(a.signature, b.signature)

    def test_signature_changes_with_content(self) -> None:
        a = cc.compile_context({"niche": "audio"})
        b = cc.compile_context({"niche": "fashion"})
        self.assertNotEqual(a.signature, b.signature)


class TestDerivatives(unittest.TestCase):
    def test_world_context_populated(self) -> None:
        ctx = cc.compile_context({
            "niche": "audio", "price_band": "premium",
            "margin_band": "high", "copy_tone": "luxury",
        })
        self.assertIsNotNone(ctx.world_context)
        t = ctx.world_context.as_tuple()
        self.assertEqual(t, ("audio", "premium", "high", "luxury"))

    def test_tree_state_populated(self) -> None:
        ctx = cc.compile_context({
            "niche": "audio", "open_launches": 2, "cash_band": "high",
        })
        self.assertIsNotNone(ctx.tree_state)
        self.assertEqual(ctx.tree_state.niche, "audio")
        self.assertEqual(ctx.tree_state.open_launches, 2)

    def test_applicability_subset(self) -> None:
        ctx = cc.compile_context({"niche": "audio",
                                    "open_launches": 5})
        self.assertEqual(
            set(ctx.applicability.keys()),
            {"niche", "price_band", "margin_band", "copy_tone"},
        )

    def test_situation_defaults(self) -> None:
        ctx = cc.compile_context({})
        self.assertIsNotNone(ctx.situation)
        self.assertEqual(ctx.situation.kills_last_7d, 0)


class TestIdempotent(unittest.TestCase):
    def test_compile_of_compiled_returns_same(self) -> None:
        first = cc.compile_context({"niche": "audio"})
        second = cc.compile_context(first)
        self.assertIs(first, second)

    def test_none_input_safe(self) -> None:
        ctx = cc.compile_context(None)
        self.assertEqual(ctx.raw["niche"], "unknown")


class TestMerge(unittest.TestCase):
    def test_merge_overlays_and_recompiles(self) -> None:
        base = cc.compile_context({"niche": "audio"})
        merged = cc.merge(base, {"price_band": "premium"})
        self.assertEqual(merged.raw["niche"], "audio")
        self.assertEqual(merged.raw["price_band"], "premium")

    def test_merge_accepts_dict_base(self) -> None:
        merged = cc.merge({"niche": "audio"}, {"copy_tone": "luxury"})
        self.assertEqual(merged.raw["niche"], "audio")
        self.assertEqual(merged.raw["copy_tone"], "luxury")


class TestSerialise(unittest.TestCase):
    def test_as_dict_covers_every_slot(self) -> None:
        ctx = cc.compile_context({"niche": "audio"})
        d = ctx.as_dict()
        for key in ("features", "world_context", "tree_state",
                     "signature", "applicability", "situation", "raw"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
