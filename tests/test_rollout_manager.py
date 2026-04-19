"""Rollout manager tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import rollout_manager as rm


class TestStart(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RolloutManager(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_start_creates_canary(self) -> None:
        r = self.m.start("r1", "audio_kill_v2", initial_pct=5)
        self.assertEqual(r.stage, "canary")
        self.assertEqual(r.current_pct, 5.0)

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.start("", "name")


class TestExposure(unittest.TestCase):
    def test_halt_blocks_exposure(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start("r", "n", initial_pct=100)
        m.rollback("r", reason="test")
        self.assertFalse(m.exposed("r", "anything"))
        tmp.cleanup()

    def test_full_exposes_everyone(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        r = m.start("r", "n", initial_pct=100)
        # Push through to full
        for _ in range(10):
            m.record_outcome("r", success=True)
        for _ in range(5):
            m.tick("r")
        # Large sample → basically everyone exposed
        self.assertTrue(m.exposed("r", "entity_a"))
        tmp.cleanup()

    def test_sticky_assignment(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start("r", "n", initial_pct=50)
        # Same entity should land in same bucket on repeat calls
        first = m.exposed("r", "entity_42")
        for _ in range(10):
            self.assertEqual(m.exposed("r", "entity_42"), first)
        tmp.cleanup()


class TestTickAndAdvance(unittest.TestCase):
    def test_advances_after_min_cycles_with_good_results(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(
            Path(tmp.name) / "r.db",
        )
        m.start(
            "r", "n",
            initial_pct=5, step_pct=20, min_cycles=2,
            ok_threshold=0.7,
        )
        for _ in range(10):
            m.record_outcome("r", success=True)
        m.tick("r"); m.tick("r")
        r = m.get("r")
        self.assertEqual(r.stage, "ramp")
        self.assertAlmostEqual(r.current_pct, 25.0)

    def test_reaches_full_stage(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start(
            "r", "n",
            initial_pct=60, step_pct=60, min_cycles=1,
            ok_threshold=0.5,
        )
        for _ in range(10):
            m.record_outcome("r", success=True)
        m.tick("r")
        self.assertEqual(m.get("r").stage, "full")
        tmp.cleanup()


class TestRollback(unittest.TestCase):
    def test_manual_rollback(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start("r", "n", initial_pct=10)
        self.assertTrue(m.rollback("r", reason="owner halted"))
        r = m.get("r")
        self.assertEqual(r.stage, "halt")
        self.assertEqual(r.halt_reason, "owner halted")

    def test_auto_rollback_on_failure_rate(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start(
            "r", "n", initial_pct=20, min_cycles=1,
            fail_threshold=0.5,
        )
        for _ in range(10):
            m.record_outcome("r", success=False)
        m.tick("r")
        self.assertEqual(m.get("r").stage, "halt")
        tmp.cleanup()

    def test_rollback_unknown_false(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        self.assertFalse(m.rollback("nope"))
        tmp.cleanup()


class TestListings(unittest.TestCase):
    def test_active_excludes_halt_and_full(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start("active", "a", initial_pct=10)
        m.start("halted", "b", initial_pct=10)
        m.rollback("halted")
        ids = [r.id for r in m.active()]
        self.assertIn("active", ids)
        self.assertNotIn("halted", ids)
        tmp.cleanup()


class TestRecord(unittest.TestCase):
    def test_record_outcome_updates_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        m.start("r", "n", initial_pct=10)
        m.record_outcome("r", success=True)
        m.record_outcome("r", success=False)
        r = m.get("r")
        self.assertEqual(r.successes, 1)
        self.assertEqual(r.failures, 1)
        tmp.cleanup()

    def test_record_unknown_returns_none(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RolloutManager(Path(tmp.name) / "r.db")
        self.assertIsNone(m.record_outcome("nope", success=True))
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
