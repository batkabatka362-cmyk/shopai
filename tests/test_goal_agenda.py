"""Goal agenda — CRUD + reprioritisation tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import goal_agenda as ga


class TestCrud(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.agenda = ga.GoalAgenda(Path(self._tmp.name) / "g.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_and_fetch(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(
                title="Launch 10 SKUs",
                description="test pet niche",
                priority=75,
            )
        self.assertIsNotNone(g.id)
        self.assertEqual(g.status, "active")
        self.assertEqual(g.priority, 75.0)
        fetched = self.agenda.get(g.id)
        self.assertEqual(fetched.title, "Launch 10 SKUs")

    def test_update_fields(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(title="X")
        updated = self.agenda.update(g.id, priority=90, status="paused")
        self.assertEqual(updated.priority, 90.0)
        self.assertEqual(updated.status, "paused")

    def test_priority_clamped_high(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(title="X")
        updated = self.agenda.update(g.id, priority=150)
        self.assertEqual(updated.priority, 100.0)

    def test_priority_clamped_low(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(title="Y")
        updated = self.agenda.update(g.id, priority=-10)
        self.assertEqual(updated.priority, 0.0)

    def test_unknown_status_rejected(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(title="X")
        with self.assertRaises(ValueError):
            self.agenda.update(g.id, status="invalid")

    def test_mark_helpers(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            g = self.agenda.register(title="X")
            self.agenda.mark_achieved(g.id)
            self.assertEqual(self.agenda.get(g.id).status, "achieved")
            g2 = self.agenda.register(title="Y")
            self.agenda.mark_abandoned(g2.id)
            self.assertEqual(self.agenda.get(g2.id).status, "abandoned")


class TestListing(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.agenda = ga.GoalAgenda(Path(self._tmp.name) / "g.db")
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            self.agenda.register(title="A", priority=90)
            self.agenda.register(title="B", priority=30)
            done = self.agenda.register(title="C", priority=50)
            self.agenda.mark_achieved(done.id)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_active_list_excludes_achieved(self) -> None:
        active = self.agenda.list_active()
        titles = [g.title for g in active]
        self.assertEqual(titles, ["A", "B"])   # sorted by priority desc

    def test_list_all_filters_by_status(self) -> None:
        achieved = self.agenda.list_all(status="achieved")
        self.assertEqual(len(achieved), 1)
        self.assertEqual(achieved[0].title, "C")


class TestReprioritise(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.agenda = ga.GoalAgenda(Path(self._tmp.name) / "g.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_near_due_goal_scored_higher(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            near = self.agenda.register(
                title="Due tomorrow", priority=50,
                due_at=time.time() + 86_400,
            )
            far = self.agenda.register(
                title="Due in 60 days", priority=50,
                due_at=time.time() + 60 * 86_400,
            )
        self.agenda.reprioritise()
        near2 = self.agenda.get(near.id)
        far2 = self.agenda.get(far.id)
        self.assertGreater(near2.priority, far2.priority)

    def test_signal_count_boosts_confidence(self) -> None:
        from unittest.mock import patch
        with patch.object(self.agenda, "_emit_status_change"):
            low = self.agenda.register(title="no signals", priority=50)
            high = self.agenda.register(title="many signals", priority=50)
        # Load both with signals
        self.agenda.update(high.id,
                           signals={"a": 1, "b": 2, "c": 3, "d": 4})
        self.agenda.reprioritise()
        high2 = self.agenda.get(high.id)
        low2 = self.agenda.get(low.id)
        self.assertGreater(high2.priority, low2.priority)


if __name__ == "__main__":
    unittest.main()
