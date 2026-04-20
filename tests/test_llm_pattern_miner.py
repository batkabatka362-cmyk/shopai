"""Tests for core.learning.llm_pattern_miner (B)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.learning.llm_pattern_miner import (
    LLMMiningReport,
    LLMPatternMiner,
    LLMProposal,
    parse_llm_proposals,
)
from core.learning.rulebook import RuleBook


def _event(**kw):
    defaults = dict(
        engine="pricing_engine",
        kpi="margin",
        kpi_value=0.15,
        ok=False,
        context={"niche": "pet"},
    )
    defaults.update(kw)
    return defaults


def _response(
    pattern="tone=luxury + price>$50",
    action="kill", evidence=5, confidence=0.8,
):
    return (
        f"PATTERN: {pattern}\n"
        f"ACTION: {action}\n"
        f"EVIDENCE: {evidence}\n"
        f"CONFIDENCE: {confidence}\n"
    )


class TestParse(unittest.TestCase):
    def test_parse_single_proposal(self):
        props, notes = parse_llm_proposals(_response())
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0].action, "kill")
        self.assertEqual(props[0].evidence, 5)

    def test_parse_multiple(self):
        raw = (
            _response(pattern="a")
            + "\n"
            + _response(
                pattern="b", action="replay",
                evidence=10,
            )
        )
        props, _ = parse_llm_proposals(raw)
        self.assertEqual(len(props), 2)

    def test_empty_response(self):
        props, notes = parse_llm_proposals("")
        self.assertEqual(props, [])
        self.assertTrue(any(
            "empty" in n for n in notes
        ))

    def test_junk_response(self):
        props, notes = parse_llm_proposals(
            "I think you should buy pet feeders.",
        )
        self.assertEqual(props, [])
        self.assertTrue(any(
            "no proposals" in n for n in notes
        ))

    def test_confidence_out_of_range_rejected(self):
        raw = _response(confidence=2.0)
        props, notes = parse_llm_proposals(raw)
        self.assertEqual(props, [])
        self.assertTrue(any(
            "rejected" in n for n in notes
        ))

    def test_evidence_zero_rejected(self):
        raw = _response(evidence=0)
        props, notes = parse_llm_proposals(raw)
        self.assertEqual(props, [])

    def test_case_insensitive_action(self):
        raw = _response(action="REPLAY")
        props, _ = parse_llm_proposals(raw)
        self.assertEqual(props[0].action, "replay")

    def test_empty_pattern_rejected(self):
        raw = (
            "PATTERN:   \n"
            "ACTION: kill\n"
            "EVIDENCE: 3\n"
            "CONFIDENCE: 0.9\n"
        )
        props, notes = parse_llm_proposals(raw)
        self.assertEqual(props, [])


class TestConfig(unittest.TestCase):
    def test_bad_cost_cap(self):
        with self.assertRaises(ValueError):
            LLMPatternMiner(call_cost_usd_cap=-0.1)

    def test_bad_calls_cap(self):
        with self.assertRaises(ValueError):
            LLMPatternMiner(calls_per_sweep_cap=0)

    def test_bad_batch(self):
        with self.assertRaises(ValueError):
            LLMPatternMiner(batch_size=0)

    def test_bad_min_conf(self):
        with self.assertRaises(ValueError):
            LLMPatternMiner(
                min_confidence_for_propose=1.5,
            )


class TestMineWithoutClient(unittest.TestCase):
    def test_no_client_noop(self):
        m = LLMPatternMiner(llm_client=None)
        report = m.mine([_event()])
        self.assertEqual(report.skipped_reason, "no_llm_client")
        self.assertEqual(report.proposals_emitted, 0)

    def test_no_events_noop(self):
        m = LLMPatternMiner(
            llm_client=lambda p: _response(),
        )
        report = m.mine([])
        self.assertEqual(report.skipped_reason, "no_events")


class TestMineWithClient(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = RuleBook(
            db_path=Path(self._tmp.name) / "rb.db",
            min_evidence_for_active=3,
        )

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_happy_path_proposes_rule(self):
        client = MagicMock(
            return_value=_response(evidence=5),
        )
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
            batch_size=100,
        )
        report = miner.mine([_event()] * 10)
        self.assertEqual(report.llm_calls, 1)
        self.assertEqual(report.proposals_emitted, 1)
        rules = self.book.by_status("proposed")
        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0].origin, "llm_pattern_miner",
        )

    def test_batches_large_input(self):
        client = MagicMock(
            side_effect=[_response(), _response()],
        )
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
            batch_size=5,
            calls_per_sweep_cap=5,
            call_cost_usd_cap=10.0,
        )
        report = miner.mine([_event()] * 10)
        self.assertEqual(report.llm_calls, 2)

    def test_call_cap_stops_iteration(self):
        client = MagicMock(return_value=_response())
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
            batch_size=5,
            calls_per_sweep_cap=1,
            call_cost_usd_cap=10.0,
        )
        miner.mine([_event()] * 50)
        self.assertEqual(client.call_count, 1)

    def test_cost_cap_stops_iteration(self):
        client = MagicMock(return_value=_response())
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
            batch_size=5,
            calls_per_sweep_cap=10,
            call_cost_usd_cap=0.001,
            cost_estimator=lambda n: 0.002,
        )
        report = miner.mine([_event()] * 50)
        self.assertEqual(client.call_count, 0)
        self.assertTrue(
            any("cost cap" in n for n in report.notes),
        )

    def test_min_confidence_filters(self):
        client = MagicMock(
            return_value=_response(confidence=0.4),
        )
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
            min_confidence_for_propose=0.7,
        )
        report = miner.mine([_event()] * 5)
        self.assertEqual(report.proposals_emitted, 0)
        self.assertTrue(
            any(
                "low-confidence" in n
                for n in report.notes
            ),
        )

    def test_client_exception_captured(self):
        client = MagicMock(
            side_effect=RuntimeError("groq 500"),
        )
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=self.book,
        )
        report = miner.mine([_event()] * 5)
        self.assertEqual(report.proposals_emitted, 0)
        self.assertTrue(
            any(
                "groq 500" in n for n in report.notes
            ),
        )

    def test_rulebook_exception_captured(self):
        client = MagicMock(return_value=_response())
        book = MagicMock()
        book.propose.side_effect = RuntimeError(
            "db gone",
        )
        miner = LLMPatternMiner(
            llm_client=client,
            rulebook=book,
        )
        report = miner.mine([_event()] * 3)
        self.assertEqual(report.proposals_emitted, 0)
        self.assertTrue(
            any(
                "rulebook.propose" in n
                for n in report.notes
            ),
        )


class TestDicts(unittest.TestCase):
    def test_proposal_dict(self):
        p = LLMProposal(
            pattern="x", action="kill",
            evidence=5, confidence=0.8,
        )
        self.assertIn("pattern", p.as_dict())

    def test_report_dict(self):
        r = LLMMiningReport(
            examined=3, llm_calls=1,
            cost_usd=0.01, proposals_emitted=2,
        )
        self.assertIn("proposals", r.as_dict())


if __name__ == "__main__":
    unittest.main()
