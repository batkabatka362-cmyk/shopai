"""Intent parser tests."""
from __future__ import annotations

import unittest

from core.brain import intent_parser as ip


class TestLaunch(unittest.TestCase):
    def test_launch_with_budget_and_niche(self) -> None:
        r = ip.parse("launch blue widget $20/day audio")
        self.assertEqual(r.verb, "launch")
        self.assertEqual(r.args.get("budget_day"), 20.0)
        self.assertEqual(r.args.get("niche"), "audio")
        self.assertGreater(r.confidence, 0.5)

    def test_launch_with_dollarless_budget(self) -> None:
        r = ip.parse("launch premium speaker 30 a day")
        self.assertEqual(r.verb, "launch")
        self.assertEqual(r.args.get("budget_day"), 30.0)

    def test_launch_extracts_product(self) -> None:
        r = ip.parse("launch the red mug at $15 in fashion")
        self.assertEqual(r.verb, "launch")
        self.assertIn("product", r.args)


class TestKill(unittest.TestCase):
    def test_kill_with_roas_threshold(self) -> None:
        r = ip.parse("kill anything under 1.5 roas after 3 days")
        self.assertEqual(r.verb, "kill")
        self.assertEqual(r.args.get("roas_below"), 1.5)
        self.assertEqual(r.args.get("after_days"), 3.0)

    def test_kill_simple(self) -> None:
        r = ip.parse("stop the audio campaign")
        self.assertEqual(r.verb, "kill")
        self.assertEqual(r.args.get("niche"), "audio")


class TestScale(unittest.TestCase):
    def test_scale_with_percent(self) -> None:
        r = ip.parse("scale audio by 50%")
        self.assertEqual(r.verb, "scale")
        self.assertEqual(r.args.get("factor_pct"), 50.0)


class TestPrice(unittest.TestCase):
    def test_price_extracts_dollar_amount(self) -> None:
        r = ip.parse("set price to $29.99")
        self.assertEqual(r.verb, "price")
        self.assertAlmostEqual(r.args.get("price_usd"), 29.99)


class TestAsk(unittest.TestCase):
    def test_ask_recognised(self) -> None:
        r = ip.parse("why did audio launches fail last week?")
        self.assertEqual(r.verb, "ask")
        self.assertIn("question", r.args)


class TestGoal(unittest.TestCase):
    def test_goal_captures_text(self) -> None:
        r = ip.parse("new goal scale to $10k/month in fashion")
        self.assertEqual(r.verb, "goal")
        self.assertIn("$10k/month", r.args.get("text", ""))


class TestUnknown(unittest.TestCase):
    def test_empty_input(self) -> None:
        r = ip.parse("")
        self.assertEqual(r.verb, "unknown")
        self.assertEqual(r.confidence, 0.0)

    def test_gibberish_suggests_nothing_or_closest(self) -> None:
        r = ip.parse("qwerty asdf zxcv")
        self.assertEqual(r.verb, "unknown")


class TestSuggestions(unittest.TestCase):
    def test_suggestions_include_closest_verbs(self) -> None:
        r = ip.parse("why bother")       # matches "ask"
        # "why" is in the ask keyword list, so verb=ask not unknown
        self.assertEqual(r.verb, "ask")


class TestCustomVerb(unittest.TestCase):
    def test_register_custom_verb_fires_first(self) -> None:
        def magic_handler(text):
            if "abracadabra" in text:
                return {"found": True}
            return None
        ip.register_verb("magic", magic_handler)
        try:
            r = ip.parse("run abracadabra please")
            self.assertEqual(r.verb, "magic")
            self.assertTrue(r.args.get("found"))
        finally:
            # Clean up the custom verb
            ip._CUSTOM_VERBS.pop("magic", None)


class TestKnownVerbs(unittest.TestCase):
    def test_known_verbs_lists_builtins(self) -> None:
        verbs = ip.known_verbs()
        self.assertIn("launch", verbs)
        self.assertIn("kill", verbs)
        self.assertIn("ask", verbs)


if __name__ == "__main__":
    unittest.main()
