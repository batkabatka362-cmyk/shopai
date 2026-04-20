"""Tests for core.learning.rulebook — Track 1a."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.learning.rulebook import (
    Rule,
    RuleBook,
    get_rulebook,
    reset_rulebook_for_tests,
)


def _book(tmp, **kw):
    defaults = dict(
        db_path=Path(tmp) / "rb.db",
        min_evidence_for_active=3,
        min_win_rate_for_active=0.60,
        kill_after_applied=5,
        kill_win_rate_floor=0.30,
    )
    defaults.update(kw)
    return RuleBook(**defaults)


class TestConfig(unittest.TestCase):
    def test_bad_min_evidence(self):
        with self.assertRaises(ValueError):
            RuleBook(min_evidence_for_active=0)

    def test_bad_win_rate_range(self):
        with self.assertRaises(ValueError):
            RuleBook(min_win_rate_for_active=1.5)


class TestPropose(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = _book(self._tmp.name)

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_propose_creates_rule(self):
        r = self.book.propose(
            origin="launch_learner",
            pattern="roas_below_1.5",
            action="kill_campaign",
            evidence_count=2,
        )
        self.assertEqual(r.status, "proposed")
        self.assertEqual(r.evidence_count, 2)
        self.assertEqual(r.applied_count, 0)

    def test_propose_idempotent_accumulates_evidence(self):
        a = self.book.propose(
            origin="x", pattern="p", action="a",
            evidence_count=1,
        )
        b = self.book.propose(
            origin="x", pattern="p", action="a",
            evidence_count=3,
        )
        self.assertEqual(a.rule_id, b.rule_id)
        self.assertEqual(b.evidence_count, 4)

    def test_propose_missing_fields_raises(self):
        with self.assertRaises(ValueError):
            self.book.propose(
                origin="", pattern="p", action="a",
            )


class TestOutcomeFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = _book(self._tmp.name)
        self.rule = self.book.propose(
            origin="x", pattern="p", action="a",
            evidence_count=2,
        )

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_win_bumps_counters(self):
        r = self.book.record_outcome(
            self.rule.rule_id, won=True,
        )
        self.assertEqual(r.applied_count, 1)
        self.assertEqual(r.wins, 1)
        self.assertGreater(r.win_rate_ema, 0.5)

    def test_auto_promote_to_active(self):
        # 2 evidence + 1 applied = 3 → meets min_evidence=3
        # EMA after 1 win = 0.2*1 + 0.8*0.5 = 0.6 → just at
        # floor
        r = self.book.record_outcome(
            self.rule.rule_id, won=True,
        )
        self.assertEqual(r.status, "active")

    def test_auto_kill_on_low_win_rate(self):
        # Propose + promote quickly, then lose 5 in a row
        rid = self.rule.rule_id
        # Push to active first
        self.book.record_outcome(rid, won=True)
        # Now lose 5
        for _ in range(5):
            self.book.record_outcome(rid, won=False)
        r = self.book.get(rid)
        self.assertEqual(r.status, "killed")

    def test_confidence_bounded(self):
        r = self.book.record_outcome(
            self.rule.rule_id, won=True,
        )
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)


class TestStatusTransitions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = _book(self._tmp.name)

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_manual_set_status(self):
        r = self.book.propose(
            origin="o", pattern="p", action="a",
        )
        r2 = self.book.set_status(
            r.rule_id, "deprecated",
        )
        self.assertEqual(r2.status, "deprecated")

    def test_invalid_status_raises(self):
        r = self.book.propose(
            origin="o", pattern="p", action="a",
        )
        with self.assertRaises(ValueError):
            self.book.set_status(r.rule_id, "nonsense")


class TestQueries(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = _book(self._tmp.name)

    def tearDown(self):
        self.book.close()
        self._tmp.cleanup()

    def test_by_status_filters(self):
        self.book.propose(
            origin="a", pattern="p1", action="x",
        )
        r2 = self.book.propose(
            origin="a", pattern="p2", action="y",
        )
        self.book.set_status(r2.rule_id, "killed")
        self.assertEqual(
            len(self.book.by_status("proposed")), 1,
        )
        self.assertEqual(
            len(self.book.by_status("killed")), 1,
        )

    def test_top_by_confidence_sorted(self):
        r1 = self.book.propose(
            origin="a", pattern="p1", action="x",
        )
        r2 = self.book.propose(
            origin="a", pattern="p2", action="y",
        )
        # r1 gets 5 wins → high confidence
        for _ in range(5):
            self.book.record_outcome(r1.rule_id, won=True)
        top = self.book.top_by_confidence(limit=2)
        self.assertEqual(top[0].rule_id, r1.rule_id)

    def test_stats_shape(self):
        self.book.propose(
            origin="a", pattern="p", action="x",
        )
        s = self.book.stats()
        self.assertEqual(s["total_rules"], 1)
        self.assertIn("proposed", s["by_status"])


class TestSingleton(unittest.TestCase):
    def test_singleton_reused(self):
        reset_rulebook_for_tests()
        try:
            a = get_rulebook()
            b = get_rulebook()
            self.assertIs(a, b)
        finally:
            reset_rulebook_for_tests()


class TestDict(unittest.TestCase):
    def test_as_dict(self):
        r = Rule(
            rule_id="r", origin="o",
            pattern="p", action="a",
        )
        d = r.as_dict()
        self.assertIn("confidence", d)
        self.assertIn("rule_id", d)


if __name__ == "__main__":
    unittest.main()
