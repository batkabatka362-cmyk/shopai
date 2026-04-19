"""Deliberation — three-agent flow with stubbed LLM."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import deliberation as dl


class _FakeResult:
    def __init__(self, text="", ok=True, adapter="groq", model="llama"):
        self.ok = ok
        self.data = {"text": text}
        self.error = None
        self.adapter = adapter
        self.model = model
        self.latency_ms = 90
        self.tokens_out = 40


_BULL_REPLY = "We should proceed: ROAS 2.4 sustained, 4 wins out of 5 launches."
_BEAR_REPLY = "We should reject: sample size is tiny, competitor just cut price."
_JUDGE_REPLY = '{"verdict":"proceed","confidence":0.72,"rationale":"Bull cites stronger base rate."}'


class TestFullDeliberation(unittest.TestCase):
    def _fake_execute(self, capability, params=None, context=None, **kw):
        msgs = params.get("messages") if params else []
        sys = next((m["content"] for m in msgs if m["role"] == "system"), "")
        if "BULL" in sys:
            return _FakeResult(text=_BULL_REPLY)
        if "BEAR" in sys:
            return _FakeResult(text=_BEAR_REPLY)
        if "JUDGE" in sys:
            return _FakeResult(text=_JUDGE_REPLY)
        return _FakeResult(ok=False, error="unknown prompt")

    def test_three_agents_fire_and_produce_verdict(self) -> None:
        with patch("core.adapters.router.SmartRouter.execute",
                   side_effect=self._fake_execute):
            v = dl.deliberate(
                proposal="scale launch X to $200/day",
                stake_usd=600.0,
            )
        self.assertEqual(v.verdict, "proceed")
        self.assertAlmostEqual(v.confidence, 0.72)
        self.assertIn("base rate", v.rationale)
        self.assertIsNotNone(v.bull)
        self.assertIsNotNone(v.bear)
        self.assertIsNotNone(v.judge)

    def test_low_stake_short_circuits(self) -> None:
        with patch("core.adapters.router.SmartRouter.execute",
                   return_value=_FakeResult(text=_JUDGE_REPLY)):
            v = dl.deliberate(
                proposal="tiny spend change",
                stake_usd=20.0,
            )
        # Bull/Bear not fired
        self.assertIsNone(v.bull)
        self.assertIsNone(v.bear)
        self.assertIsNotNone(v.judge)
        self.assertEqual(v.verdict, "proceed")

    def test_empty_proposal_returns_hold(self) -> None:
        v = dl.deliberate("", stake_usd=500)
        self.assertEqual(v.verdict, "hold")
        self.assertEqual(v.confidence, 0.0)

    def test_unparseable_judge_defaults_to_hold(self) -> None:
        def broken_exec(capability, params=None, context=None, **kw):
            msgs = params.get("messages") if params else []
            sys = next((m["content"] for m in msgs if m["role"] == "system"), "")
            if "JUDGE" in sys:
                return _FakeResult(text="not valid json")
            return _FakeResult(text="argument")
        with patch("core.adapters.router.SmartRouter.execute",
                   side_effect=broken_exec):
            v = dl.deliberate(proposal="x", stake_usd=500)
        self.assertEqual(v.verdict, "hold")


class TestParsers(unittest.TestCase):
    def test_parse_judgment_strips_fence(self) -> None:
        text = "```json\n{\"verdict\":\"reject\",\"confidence\":0.4}\n```"
        out = dl._parse_judgment(text)
        self.assertEqual(out.get("verdict"), "reject")

    def test_parse_judgment_empty_on_malformed(self) -> None:
        self.assertEqual(dl._parse_judgment("not json"), {})
        self.assertEqual(dl._parse_judgment(""), {})


class TestContextFormatting(unittest.TestCase):
    def test_collapses_memory_rows(self) -> None:
        mems = [
            {"id": 1, "category": "launch", "action": "scale",
             "score": 4.0, "content": {"niche": "audio"}},
            {"id": 2, "category": "order", "action": "purchase",
             "score": 5.0, "content": "raw text"},
        ]
        out = dl._format_context(mems)
        self.assertIn("[#1]", out)
        self.assertIn("launch/scale", out)
        self.assertIn("[#2]", out)


if __name__ == "__main__":
    unittest.main()
