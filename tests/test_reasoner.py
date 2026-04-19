"""Reasoner — parsing + flow tests with a stubbed LLM router.

The heavy lifting is LLM-dependent, so we stub the router entirely
and focus on the chain's orchestration: memory pull, step ordering,
JSON parsing, and error isolation.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import reasoner


class _FakeResult:
    def __init__(self, ok=True, text="", error=None,
                 adapter="fake", model="fake", tokens_out=10):
        self.ok = ok
        self.data = {"text": text}
        self.error = error
        self.adapter = adapter
        self.model = model
        self.tokens_out = tokens_out
        self.latency_ms = 100.0


_RESEARCH = "• Rule A active 5 uses\n• Rule B active 3 uses\n• No wins yet"
_HYP = """[
  {"id":"h1","claim":"Test hypothesis one","impact":"high"},
  {"id":"h2","claim":"Second hypothesis","impact":"med"}
]"""
_TEST = """[
  {"id":"h1","test":"Launch two SKUs","signal":"ROAS after 3 days","cost_usd":60},
  {"id":"h2","test":"Email list subset","signal":"CTR","cost_usd":0}
]"""
_EVAL = """[
  {"id":"h2","rank":1,"rationale":"cheap signal"},
  {"id":"h1","rank":2,"rationale":"costly but high impact"}
]"""


class TestReasonerFlow(unittest.TestCase):
    def _fake_execute(self, capability, params=None, context=None, **kw):
        msgs = params.get("messages") if params else []
        prompt = msgs[0].get("content", "") if msgs else ""
        if "research agent" in prompt:
            return _FakeResult(text=_RESEARCH)
        if "hypothesis-generation" in prompt:
            return _FakeResult(text=_HYP)
        if "test-design" in prompt:
            return _FakeResult(text=_TEST)
        if "evaluation agent" in prompt:
            return _FakeResult(text=_EVAL)
        return _FakeResult(ok=False, error="unknown prompt")

    def test_full_chain_returns_ranked_plan(self) -> None:
        with patch("core.brain.reasoner._pull_memories", return_value=[]), \
             patch("core.adapters.router.SmartRouter.execute",
                   side_effect=self._fake_execute):
            out = reasoner.reason("should we scale the audio niche?")
        self.assertEqual(out.question, "should we scale the audio niche?")
        self.assertIn("Rule A", out.summary)
        self.assertEqual(len(out.hypotheses), 2)
        self.assertEqual(out.hypotheses[0]["id"], "h1")
        # h2 ranked first by evaluator → should lead
        self.assertEqual(out.ranked[0]["id"], "h2")
        self.assertEqual(out.ranked[0]["rank"], 1)
        # Four steps recorded
        self.assertEqual(len(out.steps), 4)
        self.assertEqual([s.phase for s in out.steps],
                         ["research", "hypothesize", "test", "evaluate"])

    def test_degenerate_question_is_safe(self) -> None:
        with patch("core.brain.reasoner._pull_memories", return_value=[]):
            out = reasoner.reason("")
        self.assertEqual(out.question, "")
        self.assertEqual(out.hypotheses, [])
        self.assertEqual(out.ranked, [])

    def test_llm_failure_returns_empty_parts(self) -> None:
        def bad(*a, **k):
            return _FakeResult(ok=False, error="upstream 500")
        with patch("core.brain.reasoner._pull_memories", return_value=[]), \
             patch("core.adapters.router.SmartRouter.execute", side_effect=bad):
            out = reasoner.reason("why is X failing?")
        # Research + hypothesize phases each recorded an error but flow
        # didn't crash.
        errors = [s.error for s in out.steps]
        self.assertTrue(any(e and "upstream" in e for e in errors))


class TestParsers(unittest.TestCase):
    def test_parse_hypotheses_drops_malformed(self) -> None:
        text = '[{"id":"h1","claim":"good","impact":"high"}, "bad entry"]'
        hyp = reasoner._parse_hypotheses(text)
        self.assertEqual(len(hyp), 1)
        self.assertEqual(hyp[0]["id"], "h1")

    def test_attach_tests_populates_fields(self) -> None:
        hyp = [{"id": "h1", "claim": "c"}]
        reasoner._attach_tests(
            hyp,
            '[{"id":"h1","test":"launch 2 SKUs","signal":"CTR","cost_usd":50}]',
        )
        self.assertEqual(hyp[0]["test"], "launch 2 SKUs")
        self.assertEqual(hyp[0]["cost_usd"], 50.0)

    def test_parse_ranked_preserves_hypotheses_order_on_missing(self) -> None:
        hyp = [{"id": "h1", "claim": "c1"}, {"id": "h2", "claim": "c2"}]
        ranked = reasoner._parse_ranked("not json", hyp)
        self.assertEqual(len(ranked), 2)


if __name__ == "__main__":
    unittest.main()
