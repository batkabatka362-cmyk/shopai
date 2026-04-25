"""Inner monologue tests."""
from __future__ import annotations

import unittest

from core.brain import inner_monologue as im


class TestBasic(unittest.TestCase):
    def setUp(self) -> None:
        self.m = im.InnerMonologue()

    def test_say_returns_incrementing_seq(self) -> None:
        s1 = self.m.say("planner", "hello")
        s2 = self.m.say("debate", "world")
        self.assertEqual(s2, s1 + 1)

    def test_entries_preserves_order(self) -> None:
        self.m.say("a", "1")
        self.m.say("b", "2")
        self.m.say("c", "3")
        thoughts = [u.thought for u in self.m.entries()]
        self.assertEqual(thoughts, ["1", "2", "3"])

    def test_speaker_filter(self) -> None:
        self.m.say("a", "1")
        self.m.say("b", "2")
        self.m.say("a", "3")
        a_thoughts = [u.thought for u in self.m.entries(speaker="a")]
        self.assertEqual(a_thoughts, ["1", "3"])

    def test_since_seq_filter(self) -> None:
        s1 = self.m.say("a", "1")
        self.m.say("a", "2")
        self.m.say("a", "3")
        after = self.m.entries(since_seq=s1)
        self.assertEqual([u.thought for u in after], ["2", "3"])


class TestAside(unittest.TestCase):
    def setUp(self) -> None:
        self.m = im.InnerMonologue()

    def test_aside_attaches_to_last_utterance(self) -> None:
        self.m.say("planner", "considering scale")
        self.assertTrue(self.m.aside({"score": 0.87}))
        last = self.m.entries()[-1]
        self.assertEqual(last.aside, {"score": 0.87})

    def test_aside_without_prior_utterance_returns_false(self) -> None:
        self.assertFalse(self.m.aside({"x": 1}))


class TestCheckpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.m = im.InnerMonologue()

    def test_since_checkpoint_returns_tail(self) -> None:
        self.m.say("planner", "pre")
        self.m.checkpoint("start_debate")
        self.m.say("bull", "A")
        self.m.say("bear", "B")
        tail = self.m.since_checkpoint("start_debate")
        self.assertEqual(len(tail), 2)
        self.assertEqual([u.thought for u in tail], ["A", "B"])

    def test_unknown_checkpoint_empty(self) -> None:
        self.m.say("x", "y")
        self.assertEqual(self.m.since_checkpoint("nowhere"), [])


class TestBounded(unittest.TestCase):
    def test_max_entries_discards_oldest(self) -> None:
        m = im.InnerMonologue(max_entries=3)
        for i in range(5):
            m.say("x", str(i))
        thoughts = [u.thought for u in m.entries()]
        self.assertEqual(thoughts, ["2", "3", "4"])


class TestReset(unittest.TestCase):
    def test_reset_clears_and_returns_count(self) -> None:
        m = im.InnerMonologue()
        for _ in range(3):
            m.say("x", "t")
        self.assertEqual(m.reset(), 3)
        self.assertEqual(len(m), 0)


class TestRender(unittest.TestCase):
    def test_render_markdown_includes_speakers(self) -> None:
        m = im.InnerMonologue()
        m.say("planner", "evaluating kill")
        m.aside({"roas": 1.2})
        m.checkpoint("post_deliberation")
        m.say("debate", "kill is aggressive")
        md = m.render_markdown()
        self.assertIn("planner", md)
        self.assertIn("debate", md)
        self.assertIn("roas=1.2", md)
        self.assertIn("post_deliberation", md)

    def test_render_filters_speakers(self) -> None:
        m = im.InnerMonologue()
        m.say("a", "keep")
        m.say("b", "drop")
        md = m.render_markdown(speakers=["a"])
        self.assertIn("keep", md)
        self.assertNotIn("drop", md)


class TestSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self) -> None:
        self.assertIs(im.monologue(), im.monologue())


if __name__ == "__main__":
    unittest.main()
