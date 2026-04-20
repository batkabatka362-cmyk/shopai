"""Tests for core.memory.freshness_tracker — Track 8."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory.freshness_tracker import (
    FreshnessRecord,
    FreshnessTracker,
    _decay,
    get_freshness_tracker,
    reset_freshness_for_tests,
)


def _build(tmp, *, now_list=None, **kw):
    defaults = dict(
        db_path=Path(tmp) / "f.db",
        decay_s=100.0,
    )
    defaults.update(kw)
    if now_list is not None:
        it = iter(now_list)
        defaults["now_fn"] = lambda: next(it, 99999.0)
    return FreshnessTracker(**defaults)


class TestDecayCurves(unittest.TestCase):
    def test_exponential_at_zero(self):
        self.assertAlmostEqual(
            _decay(0, curve="exponential", decay_s=100),
            1.0, places=4,
        )

    def test_exponential_at_decay_s(self):
        self.assertAlmostEqual(
            _decay(100, curve="exponential", decay_s=100),
            0.3679, places=3,
        )

    def test_linear_at_half(self):
        self.assertAlmostEqual(
            _decay(50, curve="linear", decay_s=100),
            0.5, places=4,
        )

    def test_linear_past_decay_clamped(self):
        self.assertEqual(
            _decay(200, curve="linear", decay_s=100),
            0.0,
        )

    def test_step_at_boundary(self):
        self.assertEqual(
            _decay(99, curve="step", decay_s=100), 1.0,
        )
        self.assertEqual(
            _decay(200, curve="step", decay_s=100), 0.0,
        )

    def test_negative_delta_returns_one(self):
        self.assertEqual(
            _decay(-5, curve="exponential", decay_s=100),
            1.0,
        )


class TestConfig(unittest.TestCase):
    def test_bad_decay(self):
        with self.assertRaises(ValueError):
            FreshnessTracker(decay_s=0)

    def test_bad_curve(self):
        with self.assertRaises(ValueError):
            FreshnessTracker(curve="sigmoid")

    def test_bad_boost_div(self):
        with self.assertRaises(ValueError):
            FreshnessTracker(access_boost_div=0)


class TestTouch(unittest.TestCase):
    def test_creates_on_first_touch(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(
                tmp, now_list=[1000.0],
            )
            rec = t.touch("source", "cj")
            self.assertEqual(rec.access_count, 1)
            self.assertEqual(rec.last_seen, 1000.0)
            t.close()

    def test_accumulates_access_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            t = _build(
                tmp, now_fn=lambda: now[0],
            )
            for i in range(3):
                now[0] = 1000.0 + i * 10
                t.touch("source", "cj")
            rec = t.get("source", "cj")
            self.assertEqual(rec.access_count, 3)
            self.assertEqual(rec.last_seen, 1020.0)
            t.close()

    def test_blank_kind_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            with self.assertRaises(ValueError):
                t.touch("", "x")
            t.close()

    def test_blank_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            with self.assertRaises(ValueError):
                t.touch("kind", "")
            t.close()


class TestRecord(unittest.TestCase):
    def test_record_external_ts(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            t.record("concept", "c-1", ts=1234.5)
            rec = t.get("concept", "c-1")
            self.assertEqual(rec.last_seen, 1234.5)
            t.close()

    def test_record_non_positive_ts_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            with self.assertRaises(ValueError):
                t.record("x", "k", ts=0)
            t.close()


class TestFreshnessScore(unittest.TestCase):
    def test_missing_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            self.assertEqual(
                t.freshness("none", "xx"), 0.0,
            )
            t.close()

    def test_fresh_row_near_one(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(
                tmp, decay_s=100.0,
                now_fn=lambda: now[0],
            )
            t.touch("k", "a")
            self.assertGreater(t.freshness("k", "a"), 0.9)
            t.close()

    def test_decays_with_time(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(
                tmp, decay_s=100.0,
                now_fn=lambda: now[0],
            )
            t.touch("k", "a")
            fresh = t.freshness("k", "a")
            now[0] = 1500.0   # 5×decay
            stale = t.freshness("k", "a")
            self.assertLess(stale, fresh)
            t.close()

    def test_access_count_boosts(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(
                tmp, decay_s=100.0,
                now_fn=lambda: now[0],
            )
            t.touch("k", "a")
            low = t.freshness("k", "a")
            for _ in range(30):
                t.touch("k", "a")
            high = t.freshness("k", "a")
            self.assertGreater(high, low)
            t.close()

    def test_linear_curve_respected(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(
                tmp, decay_s=100.0,
                curve="linear",
                now_fn=lambda: now[0],
            )
            t.touch("k", "a")
            # At exactly decay_s elapsed, freshness should
            # equal 0 × boost = 0 (linear clamps to 0)
            now[0] = 1100.0
            self.assertEqual(
                t.freshness("k", "a"), 0.0,
            )
            t.close()


class TestOldestAndStats(unittest.TestCase):
    def test_oldest_returns_ascending(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp, now_list=[
                100.0, 200.0, 300.0,
            ])
            t.touch("source", "a")
            t.touch("source", "b")
            t.touch("source", "c")
            out = t.oldest("source", limit=3)
            self.assertEqual(out[0].key, "a")
            self.assertEqual(out[-1].key, "c")
            t.close()

    def test_oldest_filters_by_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            t.touch("kind1", "a")
            t.touch("kind2", "b")
            self.assertEqual(
                len(t.oldest("kind1")), 1,
            )

    def test_stats_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _build(tmp)
            t.touch("source", "x")
            t.touch("concept", "y")
            s = t.stats()
            self.assertEqual(s["total_rows"], 2)
            self.assertEqual(s["per_kind"]["source"], 1)
            self.assertEqual(s["per_kind"]["concept"], 1)
            t.close()


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_freshness_for_tests()
        try:
            a = get_freshness_tracker()
            b = get_freshness_tracker()
            self.assertIs(a, b)
        finally:
            reset_freshness_for_tests()


class TestRecordDict(unittest.TestCase):
    def test_dict(self):
        r = FreshnessRecord(
            kind="k", key="x",
            last_seen=10.0, access_count=3,
        )
        self.assertEqual(r.as_dict()["access_count"], 3)


if __name__ == "__main__":
    unittest.main()
