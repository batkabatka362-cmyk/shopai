"""Shadow divergence tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import shadow_divergence as sd


class TestClassify(unittest.TestCase):
    def test_agrees(self) -> None:
        self.assertEqual(sd._classify("kill", "kill"), "agrees")

    def test_kind_mismatch(self) -> None:
        self.assertEqual(sd._classify("kill", "scale"), "kind_mismatch")

    def test_legacy_only(self) -> None:
        self.assertEqual(sd._classify("kill", ""), "legacy_only")

    def test_facade_only(self) -> None:
        self.assertEqual(sd._classify("", "kill"), "facade_only")

    def test_both_empty(self) -> None:
        self.assertEqual(sd._classify("", ""), "both_empty")


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.d = sd.ShadowDivergence(Path(self._tmp.name) / "sd.db")

    def tearDown(self) -> None:
        self.d.close()
        self._tmp.cleanup()


class TestRecord(TestSetup):
    def test_record_agreement(self) -> None:
        self.d.record(
            context_summary={"niche": "audio"},
            legacy_action={"kind": "kill"},
            facade_action={"kind": "kill"},
        )
        s = self.d.summary()
        self.assertEqual(s.total, 1)
        self.assertEqual(s.agreement_rate, 1.0)

    def test_record_mismatch(self) -> None:
        self.d.record(
            context_summary={"niche": "audio"},
            legacy_action={"kind": "kill"},
            facade_action={"kind": "scale"},
        )
        s = self.d.summary()
        self.assertEqual(s.agreement_rate, 0.0)
        self.assertEqual(s.by_verdict.get("kind_mismatch"), 1)
        self.assertEqual(len(s.sample_divergent), 1)

    def test_record_facade_skips(self) -> None:
        self.d.record(
            context_summary={},
            legacy_action={"kind": "kill"},
            facade_action=None,
        )
        s = self.d.summary()
        self.assertEqual(s.by_verdict.get("legacy_only"), 1)

    def test_record_legacy_skips(self) -> None:
        self.d.record(
            context_summary={},
            legacy_action=None,
            facade_action={"kind": "scale"},
        )
        s = self.d.summary()
        self.assertEqual(s.by_verdict.get("facade_only"), 1)

    def test_both_empty(self) -> None:
        self.d.record(
            context_summary={},
            legacy_action=None,
            facade_action=None,
        )
        s = self.d.summary()
        self.assertEqual(s.by_verdict.get("both_empty"), 1)


class TestSummary(TestSetup):
    def test_agreement_rate(self) -> None:
        for _ in range(7):
            self.d.record(
                context_summary={},
                legacy_action={"kind": "kill"},
                facade_action={"kind": "kill"},
            )
        for _ in range(3):
            self.d.record(
                context_summary={},
                legacy_action={"kind": "kill"},
                facade_action={"kind": "scale"},
            )
        s = self.d.summary()
        self.assertEqual(s.total, 10)
        self.assertAlmostEqual(s.agreement_rate, 0.7)

    def test_lookback_filter(self) -> None:
        # Inject an ancient record by writing directly
        old = self.d.record(
            context_summary={},
            legacy_action={"kind": "a"},
            facade_action={"kind": "b"},
        )
        old.ts = 0.0
        # Recent record
        self.d.record(
            context_summary={},
            legacy_action={"kind": "c"},
            facade_action={"kind": "c"},
        )
        # Lookback 1 hour → only recent visible
        s = self.d.summary(lookback_s=3600)
        self.assertEqual(s.total, 1)
        self.assertEqual(s.by_verdict.get("agrees"), 1)

    def test_sample_size_respected(self) -> None:
        for i in range(10):
            self.d.record(
                context_summary={"i": i},
                legacy_action={"kind": "a"},
                facade_action={"kind": "b"},
            )
        s = self.d.summary(sample_size=3)
        self.assertEqual(len(s.sample_divergent), 3)


class TestRecent(TestSetup):
    def test_newest_first(self) -> None:
        for i in range(5):
            self.d.record(
                context_summary={"i": i},
                legacy_action={"kind": "a"},
                facade_action={"kind": "a"},
            )
        recent = self.d.recent(limit=3)
        self.assertEqual(len(recent), 3)
        # IDs order not stable; all pulled recently so just confirm sort
        self.assertGreaterEqual(recent[0].ts, recent[-1].ts)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "d.db"
        first = sd.ShadowDivergence(path)
        first.record(
            context_summary={"x": 1},
            legacy_action={"kind": "k"},
            facade_action={"kind": "k"},
        )
        first.close()
        second = sd.ShadowDivergence(path)
        self.assertEqual(second.summary().total, 1)
        second.close()
        tmp.cleanup()


class TestClear(TestSetup):
    def test_clear(self) -> None:
        self.d.record(
            context_summary={},
            legacy_action={"kind": "a"},
            facade_action={"kind": "a"},
        )
        self.assertEqual(self.d.clear(), 1)
        self.assertEqual(self.d.summary().total, 0)


class TestDict(TestSetup):
    def test_divergence_serialises(self) -> None:
        d = self.d.record(
            context_summary={"niche": "audio"},
            legacy_action={"kind": "a"},
            facade_action={"kind": "b"},
            legacy_note="legacy", facade_note="facade",
        )
        dd = d.as_dict()
        self.assertEqual(dd["verdict"], "kind_mismatch")
        self.assertEqual(dd["legacy_note"], "legacy")

    def test_summary_serialises(self) -> None:
        self.d.record(
            context_summary={}, legacy_action={"kind": "a"},
            facade_action={"kind": "a"},
        )
        sd_dict = self.d.summary().as_dict()
        self.assertIn("agreement_rate", sd_dict)
        self.assertIn("by_verdict", sd_dict)


if __name__ == "__main__":
    unittest.main()
