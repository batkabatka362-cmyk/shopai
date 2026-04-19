"""Self narrative tests."""
from __future__ import annotations

import unittest

from core.brain import self_narrative as sn


class TestStyle(unittest.TestCase):
    def test_empty_unknown(self) -> None:
        self.assertEqual(sn._style_from_weights(None), "unknown")
        self.assertEqual(sn._style_from_weights({}), "unknown")

    def test_growth_dominant(self) -> None:
        weights = {"roas": 0.7, "refund_rate": 0.1,
                   "cost": 0.1, "stability": 0.1}
        self.assertEqual(
            sn._style_from_weights(weights), "growth-first",
        )

    def test_cost_averse(self) -> None:
        weights = {"roas": 0.1, "refund_rate": 0.1,
                   "cost": 0.6, "stability": 0.2}
        self.assertEqual(
            sn._style_from_weights(weights), "cost-averse",
        )


class TestCompose(unittest.TestCase):
    def test_empty_composition_returns_narrative(self) -> None:
        n = sn.compose()
        self.assertEqual(n.identity_line, "ShopAI commerce executor")
        self.assertEqual(n.strengths, [])
        self.assertEqual(n.owner_style, "unknown")

    def test_strengths_included(self) -> None:
        n = sn.compose(
            task_strengths=[
                {"task_class": "kill_ad",
                 "success_rate": 0.9, "uses": 40},
            ],
        )
        self.assertIn("kill_ad", n.markdown)
        self.assertIn("kill_ad", n.identity_line)

    def test_weaknesses_included(self) -> None:
        n = sn.compose(
            task_weaknesses=[
                {"task_class": "refund_ops",
                 "success_rate": 0.3, "uses": 20},
            ],
        )
        self.assertIn("refund_ops", n.markdown)
        self.assertIn("weakest", n.identity_line)

    def test_owner_style_in_markdown(self) -> None:
        n = sn.compose(owner_weights={
            "roas": 0.6, "refund_rate": 0.1,
            "cost": 0.1, "stability": 0.2,
        })
        self.assertIn("growth-first", n.markdown)
        self.assertIn("growth-first", n.identity_line)

    def test_trend_counts(self) -> None:
        n = sn.compose(
            learning_trends=[
                {"trend": "improving"},
                {"trend": "improving"},
                {"trend": "regressing"},
            ],
        )
        self.assertIn("2 metric(s) improving", n.markdown)
        self.assertIn("1 metric(s) regressing", n.markdown)

    def test_pending_load_in_markdown(self) -> None:
        n = sn.compose(pending_load={"commitments": 3, "queue": 12})
        self.assertIn("commitments: 3", n.markdown)

    def test_memory_size_present(self) -> None:
        n = sn.compose(memory_size=12345)
        self.assertIn("12345", n.markdown)


class TestSystemPrompt(unittest.TestCase):
    def test_prompt_includes_strengths(self) -> None:
        n = sn.compose(
            task_strengths=[
                {"task_class": "kill_ad",
                 "success_rate": 0.9, "uses": 40},
            ],
        )
        self.assertIn("kill_ad", n.system_prompt)
        self.assertIn("proven at", n.system_prompt)

    def test_prompt_includes_weaknesses(self) -> None:
        n = sn.compose(
            task_weaknesses=[
                {"task_class": "refund_ops",
                 "success_rate": 0.2, "uses": 10},
            ],
        )
        self.assertIn("refund_ops", n.system_prompt)
        self.assertIn("defer", n.system_prompt)


class TestNarrator(unittest.TestCase):
    def test_all_providers_wired(self) -> None:
        narrator = sn.SelfNarrator(
            competence_provider=lambda: {
                "strengths": [
                    {"task_class": "scale", "success_rate": 0.9,
                     "uses": 30},
                ],
                "weaknesses": [
                    {"task_class": "refund", "success_rate": 0.2,
                     "uses": 10},
                ],
            },
            owner_weights_provider=lambda: {
                "roas": 0.6, "refund_rate": 0.1,
                "cost": 0.1, "stability": 0.2,
            },
            learning_provider=lambda: [
                {"trend": "improving"}, {"trend": "plateau"},
            ],
            load_provider=lambda: {"commitments": 2},
            memory_size_provider=lambda: 1000,
        )
        n = narrator.narrate()
        self.assertIn("scale", n.system_prompt)
        self.assertIn("refund", n.system_prompt)
        self.assertIn("growth-first", n.system_prompt)
        self.assertIn("1000", n.markdown)

    def test_provider_failure_falls_back(self) -> None:
        def boom():
            raise RuntimeError("x")

        narrator = sn.SelfNarrator(
            competence_provider=boom,
            owner_weights_provider=boom,
            learning_provider=boom,
            load_provider=boom,
            memory_size_provider=boom,
        )
        # Should not raise — degrade gracefully
        n = narrator.narrate()
        self.assertEqual(n.identity_line, "ShopAI commerce executor")

    def test_no_providers_gives_base_narrative(self) -> None:
        narrator = sn.SelfNarrator()
        n = narrator.narrate()
        self.assertIn("ShopAI", n.identity_line)


class TestDict(unittest.TestCase):
    def test_narrative_serialises(self) -> None:
        n = sn.compose(
            task_strengths=[
                {"task_class": "a", "success_rate": 0.8, "uses": 10},
            ],
        )
        d = n.as_dict()
        self.assertIn("identity_line", d)
        self.assertIn("markdown", d)
        self.assertIn("strengths", d)


if __name__ == "__main__":
    unittest.main()
