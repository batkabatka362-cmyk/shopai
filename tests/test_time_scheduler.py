"""Time scheduler tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import time_scheduler as ts


def _epoch_for(year: int, month: int, day: int, hour=0, minute=0) -> float:
    """Build a UTC epoch deterministically."""
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, 0)) - time.timezone


class TestRegister(unittest.TestCase):
    def test_interval_registration(self) -> None:
        s = ts.TimeScheduler()
        spec = s.register_interval("ping", seconds=60)
        self.assertEqual(spec.kind, "interval")
        self.assertEqual(spec.seconds, 60)

    def test_blank_name_raises(self) -> None:
        s = ts.TimeScheduler()
        with self.assertRaises(ValueError):
            s.register_interval("", seconds=10)

    def test_invalid_seconds_raises(self) -> None:
        s = ts.TimeScheduler()
        with self.assertRaises(ValueError):
            s.register_interval("x", seconds=0)

    def test_daily_bounds(self) -> None:
        s = ts.TimeScheduler()
        with self.assertRaises(ValueError):
            s.register_daily("x", hour=24)
        with self.assertRaises(ValueError):
            s.register_daily("x", hour=10, minute=70)

    def test_weekly_bounds(self) -> None:
        s = ts.TimeScheduler()
        with self.assertRaises(ValueError):
            s.register_weekly("x", weekday=7, hour=10)

    def test_invalid_cron_raises(self) -> None:
        s = ts.TimeScheduler()
        with self.assertRaises(ValueError):
            s.register_cron("x", pattern="bad")
        with self.assertRaises(ValueError):
            s.register_cron("x", pattern="* * * *")  # 4 fields

    def test_unregister(self) -> None:
        s = ts.TimeScheduler()
        s.register_interval("x", seconds=1)
        self.assertTrue(s.unregister("x"))
        self.assertFalse(s.unregister("x"))


class TestInterval(unittest.TestCase):
    def test_due_when_interval_passed(self) -> None:
        s = ts.TimeScheduler()
        s.register_interval("ping", seconds=60)
        # last_run_ts=0 → 60s elapsed easily
        due = s.due(now=time.time())
        names = [d.name for d in due]
        self.assertIn("ping", names)

    def test_not_due_inside_interval(self) -> None:
        s = ts.TimeScheduler()
        s.register_interval("ping", seconds=60)
        s.mark_ran("ping", ts=time.time())
        due = s.due(now=time.time() + 10)
        self.assertEqual(due, [])

    def test_due_again_after_interval(self) -> None:
        s = ts.TimeScheduler()
        s.register_interval("ping", seconds=60)
        s.mark_ran("ping", ts=time.time() - 70)
        self.assertEqual([d.name for d in s.due()], ["ping"])


class TestDaily(unittest.TestCase):
    def test_due_after_anchor(self) -> None:
        s = ts.TimeScheduler()
        s.register_daily("morning", hour=9, minute=0)
        # Set 'now' to 10am UTC today; last_run_ts=0 → due
        now = ts._anchor_today(time.time(), 10, 0)
        due = s.due(now=now)
        self.assertIn("morning", [d.name for d in due])

    def test_not_due_before_anchor(self) -> None:
        s = ts.TimeScheduler()
        s.register_daily("evening", hour=20, minute=0)
        # 'now' = 1pm; anchor 8pm not yet reached
        now = ts._anchor_today(time.time(), 13, 0)
        due = s.due(now=now)
        self.assertNotIn("evening", [d.name for d in due])

    def test_not_due_after_run(self) -> None:
        s = ts.TimeScheduler()
        s.register_daily("morning", hour=9, minute=0)
        now = ts._anchor_today(time.time(), 10, 0)
        s.mark_ran("morning", ts=now)
        # Same 'now' second time → already ran today
        self.assertEqual(s.due(now=now + 60), [])


class TestWeekly(unittest.TestCase):
    def test_due_on_weekday(self) -> None:
        s = ts.TimeScheduler()
        # Register Monday 9am
        s.register_weekly("standup", weekday=0, hour=9)
        # Compute "now" at this Monday 10am
        now = ts._anchor_this_week(time.time(), 0, 10, 0)
        self.assertIn(
            "standup", [d.name for d in s.due(now=now)],
        )

    def test_not_due_other_weekday(self) -> None:
        s = ts.TimeScheduler()
        s.register_weekly("standup", weekday=0, hour=9)
        # Wednesday 10am
        now = ts._anchor_this_week(time.time(), 2, 10, 0)
        s.mark_ran("standup", ts=now)
        # Same week — already ran
        self.assertNotIn(
            "standup", [d.name for d in s.due(now=now + 60)],
        )


class TestCron(unittest.TestCase):
    def test_match_every_minute(self) -> None:
        s = ts.TimeScheduler()
        s.register_cron("each_min", pattern="* * *")
        due = s.due(now=time.time())
        self.assertIn("each_min", [d.name for d in due])

    def test_match_specific_minute(self) -> None:
        # Build "now" at HH:30 deliberately
        now = time.time()
        struct = time.gmtime(now)
        target = (
            now - (struct.tm_min - 30) * 60
            if struct.tm_min != 30 else now
        )
        s = ts.TimeScheduler()
        s.register_cron("half_hour", pattern="30 * *")
        due = s.due(now=target)
        names = [d.name for d in due]
        self.assertIn("half_hour", names)

    def test_step_pattern(self) -> None:
        # Every 15 minutes
        s = ts.TimeScheduler()
        s.register_cron("every_15", pattern="*/15 * *")
        # Build "now" at minute 30 — multiple of 15
        now = time.time()
        struct = time.gmtime(now)
        anchor = now - (struct.tm_min - 30) * 60 if struct.tm_min != 30 else now
        due = s.due(now=anchor)
        self.assertIn("every_15", [d.name for d in due])

    def test_dedupe_within_minute(self) -> None:
        s = ts.TimeScheduler()
        s.register_cron("each_min", pattern="* * *")
        # Use a fixed epoch rounded to a minute boundary so
        # now+5 and now are guaranteed to share the same minute
        # bucket (avoiding wall-clock flakiness near XX:YY:58 etc.).
        now = 1_760_000_000.0   # exactly on a minute boundary
        s.mark_ran("each_min", ts=now)
        # Same minute — should NOT be due
        self.assertEqual(s.due(now=now + 5), [])
        # Next minute — due again
        self.assertEqual(
            [d.name for d in s.due(now=now + 70)],
            ["each_min"],
        )


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "s.db"
        first = ts.TimeScheduler(db_path=path)
        first.register_interval("ping", seconds=60)
        first.mark_ran("ping", ts=12345.0)
        first.close()
        second = ts.TimeScheduler(db_path=path)
        loaded = second.tasks()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].last_run_ts, 12345.0)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = ts.TimeScheduler()
        s.register_interval("a", seconds=10)
        s.register_daily("b", hour=9)
        st = s.stats()
        self.assertEqual(st["total_tasks"], 2)
        self.assertEqual(st["by_kind"]["interval"], 1)
        self.assertEqual(st["by_kind"]["daily"], 1)


class TestDict(unittest.TestCase):
    def test_spec_serialises(self) -> None:
        s = ts.TimeScheduler()
        spec = s.register_daily(
            "x", hour=9, payload={"task": "digest"},
        )
        d = spec.as_dict()
        self.assertEqual(d["kind"], "daily")
        self.assertEqual(d["hour"], 9)
        self.assertEqual(d["payload"]["task"], "digest")


if __name__ == "__main__":
    unittest.main()
