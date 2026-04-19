"""Policy library tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import policy_library as pl


class TestRegisterAndGet(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = pl.PolicyLibrary(Path(self._tmp.name) / "p.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_then_fetch(self) -> None:
        self.lib.register(
            name="aggressive_kill",
            description="kill fast when ROAS below floor",
            applicability={"niche": "audio"},
            action_template={"kind": "kill", "days": 2},
            tags=["kill", "audio"],
        )
        p = self.lib.get("aggressive_kill")
        self.assertIsNotNone(p)
        self.assertEqual(p.tags, ("kill", "audio"))

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.register(
                name="   ", description="x",
                applicability={}, action_template={},
            )


class TestRecordOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = pl.PolicyLibrary(Path(self._tmp.name) / "p.db")
        self.lib.register(
            name="test",
            description="", applicability={},
            action_template={},
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_success_raises_rate(self) -> None:
        for _ in range(5):
            self.lib.record_outcome("test", success=True)
        p = self.lib.get("test")
        self.assertEqual(p.use_count, 5)
        self.assertEqual(p.success_count, 5)
        self.assertGreater(p.success_rate, 0.8)

    def test_failure_lowers_rate(self) -> None:
        for _ in range(5):
            self.lib.record_outcome("test", success=False)
        p = self.lib.get("test")
        self.assertLess(p.success_rate, 0.5)

    def test_unknown_policy_returns_none(self) -> None:
        self.assertIsNone(self.lib.record_outcome("missing", True))


class TestRetire(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = pl.PolicyLibrary(Path(self._tmp.name) / "p.db")
        self.lib.register(
            name="t", description="", applicability={},
            action_template={},
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_retire_sets_status(self) -> None:
        self.assertTrue(self.lib.retire("t", reason="obsolete"))
        p = self.lib.get("t")
        self.assertEqual(p.status, "retired")

    def test_retire_unknown_false(self) -> None:
        self.assertFalse(self.lib.retire("nope"))

    def test_retired_policy_not_proposed(self) -> None:
        self.lib.retire("t")
        matches = self.lib.propose({}, min_fit=0.0)
        self.assertEqual(matches, [])


class TestPredicate(unittest.TestCase):
    def test_literal_match(self) -> None:
        self.assertTrue(pl._matches_predicate("audio", "audio"))
        self.assertFalse(pl._matches_predicate("audio", "fashion"))

    def test_list_match(self) -> None:
        self.assertTrue(pl._matches_predicate(["a", "b"], "b"))
        self.assertFalse(pl._matches_predicate(["a", "b"], "c"))

    def test_range_gt_lt(self) -> None:
        self.assertTrue(
            pl._matches_predicate({"gt": 1.0, "lt": 2.0}, 1.5),
        )
        self.assertFalse(
            pl._matches_predicate({"gt": 1.0, "lt": 2.0}, 2.5),
        )

    def test_range_ge_le(self) -> None:
        self.assertTrue(
            pl._matches_predicate({"ge": 1.0, "le": 2.0}, 1.0),
        )
        self.assertTrue(
            pl._matches_predicate({"ge": 1.0, "le": 2.0}, 2.0),
        )

    def test_non_numeric_fails_range(self) -> None:
        self.assertFalse(
            pl._matches_predicate({"gt": 1.0}, "foo"),
        )


class TestPropose(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = pl.PolicyLibrary(Path(self._tmp.name) / "p.db")
        self.lib.register(
            name="audio_kill",
            description="", applicability={"niche": "audio"},
            action_template={"kind": "kill"},
        )
        self.lib.register(
            name="fashion_scale",
            description="", applicability={"niche": "fashion"},
            action_template={"kind": "scale"},
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_propose_matches_context(self) -> None:
        matches = self.lib.propose({"niche": "audio"})
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].policy.name, "audio_kill")

    def test_propose_ranks_by_success(self) -> None:
        for _ in range(10):
            self.lib.record_outcome("audio_kill", success=True)
        self.lib.register(
            name="audio_other",
            description="", applicability={"niche": "audio"},
            action_template={"kind": "hold"},
        )
        matches = self.lib.propose({"niche": "audio"})
        self.assertEqual(matches[0].policy.name, "audio_kill")

    def test_below_min_fit_filtered(self) -> None:
        matches = self.lib.propose(
            {"niche": "unknown"}, min_fit=0.5,
        )
        self.assertEqual(matches, [])

    def test_find_similar_no_min_fit(self) -> None:
        # No 'niche' in context → fit is 0 for both but find_similar
        # should still return (sorted by score).
        matches = self.lib.find_similar({"something": "else"}, k=5)
        self.assertEqual(len(matches), 2)


class TestTop(unittest.TestCase):
    def test_top_respects_min_uses(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        lib = pl.PolicyLibrary(Path(tmp.name) / "p.db")
        lib.register(
            name="winner", description="", applicability={},
            action_template={},
        )
        lib.register(
            name="rookie", description="", applicability={},
            action_template={},
        )
        for _ in range(5):
            lib.record_outcome("winner", success=True)
        lib.record_outcome("rookie", success=True)
        top = lib.top(min_uses=3)
        names = [p.name for p in top]
        self.assertIn("winner", names)
        self.assertNotIn("rookie", names)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        lib = pl.PolicyLibrary(Path(tmp.name) / "p.db")
        lib.register(name="a", description="",
                     applicability={}, action_template={})
        lib.register(name="b", description="",
                     applicability={}, action_template={})
        lib.retire("b")
        stats = lib.stats()
        self.assertEqual(stats["counts"].get("active"), 1)
        self.assertEqual(stats["counts"].get("retired"), 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
