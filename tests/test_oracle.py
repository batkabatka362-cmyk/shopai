"""Oracle — Q&A chain tests with stubbed router."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import oracle


class _FakeResult:
    def __init__(self, text, ok=True, adapter="groq", model="llama"):
        self.ok = ok
        self.data = {"text": text}
        self.error = None
        self.adapter = adapter
        self.model = model
        self.latency_ms = 80.0
        self.tokens_out = 40


class TestAdapterPreference(unittest.TestCase):
    def test_deep_question_prefers_deepseek(self) -> None:
        pref = oracle._adapter_preference("Why is the audio niche underperforming?")
        self.assertEqual(pref[0], "deepseek")

    def test_quick_question_prefers_groq(self) -> None:
        pref = oracle._adapter_preference("List the top 5 rules")
        self.assertEqual(pref[0], "groq")

    def test_neutral_defaults_to_groq(self) -> None:
        pref = oracle._adapter_preference("Run the cycle")
        self.assertEqual(pref[0], "groq")


class TestCitationExtraction(unittest.TestCase):
    def test_extracts_valid_ids(self) -> None:
        text = "We saw two winners [#42] and [#101]."
        mems = [{"id": 42, "category": "x"}, {"id": 101, "category": "y"}, {"id": 999}]
        cited = oracle._extract_citations(text, mems)
        self.assertEqual(cited, [42, 101])

    def test_ignores_unknown_ids(self) -> None:
        text = "See [#999] (not in memory)."
        cited = oracle._extract_citations(text, [{"id": 1}])
        self.assertEqual(cited, [])


class TestAskFlow(unittest.TestCase):
    def test_populates_answer(self) -> None:
        def fake_execute(capability, params=None, context=None, **kw):
            return _FakeResult("The audio niche is slow [#7].")
        mems = [{"id": 7, "category": "launch", "action": "scale",
                 "level": 2, "score": 4.0, "content": {"niche": "audio"}}]
        with patch("core.brain.oracle._pull_memories", return_value=mems), \
             patch("core.adapters.router.SmartRouter.execute",
                   side_effect=fake_execute):
            ans = oracle.ask("How is audio performing?")
        self.assertIn("audio", ans.text.lower())
        self.assertEqual(ans.memories_used, 1)
        self.assertEqual(ans.cited_ids, [7])
        self.assertEqual(ans.adapter, "groq")
        self.assertGreater(ans.confidence, 0)

    def test_empty_question_returns_blank_answer(self) -> None:
        ans = oracle.ask("")
        self.assertEqual(ans.text, "")
        self.assertEqual(ans.memories_used, 0)

    def test_router_failure_returns_explanation(self) -> None:
        def fake_execute(capability, params=None, context=None, **kw):
            return _FakeResult("", ok=False)
        with patch("core.brain.oracle._pull_memories", return_value=[]), \
             patch("core.adapters.router.SmartRouter.execute",
                   side_effect=fake_execute):
            ans = oracle.ask("anything")
        self.assertIn("adapter error", ans.text)


if __name__ == "__main__":
    unittest.main()
