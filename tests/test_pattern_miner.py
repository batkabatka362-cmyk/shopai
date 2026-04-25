"""Tests for core.learning.pattern_miner."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.learning.pattern_miner import (
    MiningReport,
    PatternMiner,
    _event_signature,
    _kpi_band,
)
from core.learning.rulebook import RuleBook


def _event(**kw):
    defaults = dict(
        capability_name="launch_sku",
        kpi="roas",
        kpi_value=0.9,
        ok=False,
    )
    defaults.update(kw)
    return defaults   # plain dict — miner tolerates both


class TestSignature(unittest.TestCase):
    def test_kpi_band(self):
        self.assertEqual(_kpi_band(0.1), "low")
        self.assertEqual(_kpi_band(1.0), "mid")
        self.assertEqual(_kpi_band(3.0), "high")

    def test_dict_event(self):
        sig = _event_signature(_event())
        self.assertEqual(len(sig), 4)
        self.assertEqual(sig[0], "launch_sku")
        self.assertEqual(sig[2], "mid")

    def test_dataclass_event(self):
        class _E:
            capability_name = "x"
            kpi = "y"
            kpi_value = 2.0
            ok = True
        sig = _event_signature(_E())
        self.assertEqual(sig[2], "high")


class TestMiningConfig(unittest.TestCase):
    def test_bad_min_evidence(self):
        with self.assertRaises(ValueError):
            PatternMiner(min_evidence=0)

    def test_bad_fail_rate_floor(self):
        with self.assertRaises(ValueError):
            PatternMiner(fail_rate_floor=1.5)

    def test_bad_win_rate_floor(self):
        with self.assertRaises(ValueError):
            PatternMiner(win_rate_floor=-0.1)


class TestMining(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = RuleBook(
            db_path=Path(self._tmp.name) / "rb.db",
            min_evidence_for_active=3,
        )
        self.miner = PatternMiner(
            rulebook=self.book,
            min_evidence=3,
            min_wins=3,
            fail_rate_floor=0.60,
            win_rate_floor=0.70,
        )

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_empty_events_empty_report(self):
        report = self.miner.mine([])
        self.assertEqual(report.examined, 0)
        self.assertEqual(report.proposals_emitted, 0)

    def test_low_evidence_skipped(self):
        events = [_event()] * 2
        report = self.miner.mine(events)
        self.assertEqual(report.proposals_emitted, 0)
        self.assertEqual(report.skipped_low_evidence, 1)

    def test_kill_proposal_on_repeated_failure(self):
        # 4 matching failure events = should promote to kill
        events = [_event(ok=False)] * 4
        report = self.miner.mine(events)
        self.assertEqual(report.proposals_emitted, 1)
        self.assertEqual(len(report.kill_proposals), 1)
        rid = report.kill_proposals[0]
        rule = self.book.get(rid)
        self.assertEqual(rule.action, "kill_signature")
        self.assertEqual(rule.evidence_count, 4)

    def test_replay_proposal_on_repeated_win(self):
        events = [_event(ok=True, kpi_value=2.5)] * 5
        report = self.miner.mine(events)
        self.assertEqual(report.proposals_emitted, 1)
        self.assertEqual(len(report.replay_proposals), 1)
        rid = report.replay_proposals[0]
        rule = self.book.get(rid)
        self.assertEqual(rule.action, "replay_signature")

    def test_idempotent_dedupe_bumps_evidence(self):
        # Run miner twice with same events → one rule, doubled
        # evidence
        events = [_event(ok=False)] * 4
        self.miner.mine(events)
        self.miner.mine(events)
        rules = self.book.by_status("proposed")
        self.assertEqual(len(rules), 1)
        self.assertGreaterEqual(rules[0].evidence_count, 8)

    def test_mixed_events_partial_pattern(self):
        # Bucket 1: 4 roas-mid failures → kill
        # Bucket 2: 5 roas-high wins → replay
        # Bucket 3: 2 roas-low failures → skip
        events = (
            [_event(ok=False, kpi_value=0.9)] * 4
            + [_event(ok=True, kpi_value=3.0)] * 5
            + [_event(ok=False, kpi_value=0.1)] * 2
        )
        report = self.miner.mine(events)
        self.assertEqual(report.examined, 11)
        self.assertEqual(report.unique_signatures, 3)
        self.assertEqual(report.proposals_emitted, 2)

    def test_report_as_dict(self):
        report = self.miner.mine([_event()] * 4)
        d = report.as_dict()
        self.assertIn("proposals_emitted", d)


if __name__ == "__main__":
    unittest.main()
