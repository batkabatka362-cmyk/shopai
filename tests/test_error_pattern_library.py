"""Error pattern library tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import error_pattern_library as epl


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = epl.ErrorPatternLibrary()

    def test_blank_signature_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.observe(
                signature="", remedy="r", worked=True,
            )

    def test_blank_remedy_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.observe(
                signature="s", remedy="", worked=True,
            )

    def test_observe_appends(self) -> None:
        obs = self.lib.observe(
            signature="shopify:429",
            context={"endpoint": "/orders"},
            remedy="backoff_2s",
            worked=True,
        )
        self.assertTrue(obs.worked)
        self.assertEqual(self.lib.stats()["observations"], 1)


class TestSuggest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = epl.ErrorPatternLibrary()

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(self.lib.suggest("unknown:sig"))

    def test_blank_signature_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.suggest("")

    def test_picks_highest_success_rate(self) -> None:
        # remedy A: 2/2, remedy B: 8/10
        for _ in range(2):
            self.lib.observe(
                signature="s", remedy="A", worked=True,
            )
        for i in range(10):
            self.lib.observe(
                signature="s", remedy="B", worked=(i < 8),
            )
        s = self.lib.suggest("s")
        self.assertEqual(s.remedy, "A")
        self.assertEqual(s.success_rate, 1.0)

    def test_tie_prefers_more_attempts(self) -> None:
        for _ in range(2):
            self.lib.observe(
                signature="s", remedy="A", worked=True,
            )
        for _ in range(10):
            self.lib.observe(
                signature="s", remedy="B", worked=True,
            )
        s = self.lib.suggest("s")
        self.assertEqual(s.remedy, "B")

    def test_min_attempts_filter(self) -> None:
        self.lib.observe(
            signature="s", remedy="solo", worked=True,
        )
        self.assertIsNone(
            self.lib.suggest("s", min_attempts=3),
        )

    def test_suggestions_list_sorted(self) -> None:
        self.lib.observe(
            signature="s", remedy="low", worked=False,
        )
        self.lib.observe(
            signature="s", remedy="high", worked=True,
        )
        suggs = self.lib.suggestions("s")
        self.assertEqual(suggs[0].remedy, "high")


class TestContextStripping(unittest.TestCase):
    def test_transient_fields_dropped(self) -> None:
        lib = epl.ErrorPatternLibrary()
        obs = lib.observe(
            signature="s",
            context={
                "endpoint": "/x", "ts": 12345, "request_id": "r",
            },
            remedy="r", worked=True,
        )
        self.assertNotIn("ts", obs.context_fingerprint)
        self.assertNotIn("request_id", obs.context_fingerprint)
        self.assertIn("endpoint", obs.context_fingerprint)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "e.db"
        first = epl.ErrorPatternLibrary(path)
        first.observe(
            signature="s", remedy="r", worked=True,
        )
        first.close()
        second = epl.ErrorPatternLibrary(path)
        s = second.suggest("s")
        self.assertIsNotNone(s)
        self.assertEqual(s.remedy, "r")
        second.close()
        tmp.cleanup()


class TestQueries(unittest.TestCase):
    def test_known_signatures(self) -> None:
        lib = epl.ErrorPatternLibrary()
        lib.observe(signature="a", remedy="x", worked=True)
        lib.observe(signature="b", remedy="x", worked=True)
        self.assertEqual(lib.known_signatures(), ["a", "b"])


class TestStats(unittest.TestCase):
    def test_overall_success_rate(self) -> None:
        lib = epl.ErrorPatternLibrary()
        lib.observe(signature="s", remedy="r", worked=True)
        lib.observe(signature="s", remedy="r", worked=False)
        s = lib.stats()
        self.assertEqual(s["overall_success_rate"], 0.5)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        lib = epl.ErrorPatternLibrary()
        lib.observe(signature="s", remedy="r", worked=True)
        self.assertEqual(lib.reset(), 1)
        self.assertEqual(lib.stats()["observations"], 0)


class TestDict(unittest.TestCase):
    def test_obs_serialises(self) -> None:
        lib = epl.ErrorPatternLibrary()
        obs = lib.observe(
            signature="s", remedy="r", worked=True,
        )
        d = obs.as_dict()
        self.assertEqual(d["signature"], "s")

    def test_suggestion_serialises(self) -> None:
        lib = epl.ErrorPatternLibrary()
        lib.observe(
            signature="s", remedy="r", worked=True,
        )
        s = lib.suggest("s")
        d = s.as_dict()
        self.assertIn("success_rate", d)


if __name__ == "__main__":
    unittest.main()
