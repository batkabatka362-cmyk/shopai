"""Observation stream reducer tests."""
from __future__ import annotations

import unittest

from core.brain import observation_stream_reducer as osr


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            osr.ObservationStreamReducer(window_seconds=0)

    def test_bad_buffer_raises(self) -> None:
        with self.assertRaises(ValueError):
            osr.ObservationStreamReducer(buffer_size=5)


class TestIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.r = osr.ObservationStreamReducer()

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.ingest("")

    def test_ingest_stores(self) -> None:
        self.r.ingest("order", {"amount": 29.99})
        self.assertEqual(self.r.buffered(), 1)

    def test_batch_counts(self) -> None:
        n = self.r.ingest_batch([
            {"kind": "order", "fields": {"amount": 10}},
            {"kind": "click", "fields": {}},
            {"fields": {}},  # no kind → skipped
        ])
        self.assertEqual(n, 2)


class TestReduce(unittest.TestCase):
    def setUp(self) -> None:
        self.r = osr.ObservationStreamReducer(
            window_seconds=3600,  # 1h
        )

    def test_count_correct(self) -> None:
        for _ in range(5):
            self.r.ingest("order", ts=100.0)
        for _ in range(3):
            self.r.ingest("click", ts=100.0)
        s = self.r.reduce(now=200.0)
        self.assertEqual(s.event_counts["order"], 5)
        self.assertEqual(s.event_counts["click"], 3)
        self.assertEqual(s.total_events, 8)

    def test_outside_window_excluded(self) -> None:
        self.r.ingest("order", ts=100.0)   # window cutoff: 200-3600
        self.r.ingest("order", ts=1000.0)
        # Reduce at t=5000; window cutoff 1400 → only t=1000 excluded? Let's be careful
        # With window_seconds=3600, cutoff=5000-3600=1400. Both 100 and 1000 are below 1400.
        s = self.r.reduce(now=5000.0)
        self.assertEqual(s.total_events, 0)

    def test_rate_per_hour(self) -> None:
        r = osr.ObservationStreamReducer(window_seconds=3600)
        for _ in range(10):
            r.ingest("order", ts=100.0)
        s = r.reduce(now=200.0)
        self.assertAlmostEqual(
            s.rates_per_hour["order"], 10.0, places=3,
        )


class TestAxes(unittest.TestCase):
    def test_distinct_axis(self) -> None:
        r = osr.ObservationStreamReducer(
            window_seconds=3600,
            distinct_axes=[
                osr.DistinctReducer("order", "sku"),
            ],
        )
        r.ingest("order", {"sku": "p1"}, ts=100.0)
        r.ingest("order", {"sku": "p2"}, ts=100.0)
        r.ingest("order", {"sku": "p1"}, ts=100.0)
        s = r.reduce(now=200.0)
        self.assertEqual(s.distinct_values["order.sku"], 2)

    def test_latest_axis(self) -> None:
        r = osr.ObservationStreamReducer(
            window_seconds=3600,
            latest_axes=[
                osr.LatestReducer("price", "value"),
            ],
        )
        r.ingest("price", {"value": 29.99}, ts=100.0)
        r.ingest("price", {"value": 31.50}, ts=150.0)
        r.ingest("price", {"value": 29.00}, ts=125.0)
        s = r.reduce(now=200.0)
        # Latest by ts = 150 → 31.50
        self.assertEqual(s.latest_values["price.value"], 31.50)

    def test_register_after_init(self) -> None:
        r = osr.ObservationStreamReducer()
        r.register_distinct(
            osr.DistinctReducer("order", "sku"),
        )
        r.ingest("order", {"sku": "p1"})
        s = r.reduce()
        self.assertEqual(s.distinct_values["order.sku"], 1)


class TestHashable(unittest.TestCase):
    def test_hashable_handles_nested(self) -> None:
        r = osr.ObservationStreamReducer(
            distinct_axes=[
                osr.DistinctReducer("event", "tag"),
            ],
        )
        # list + dict fields should still work
        r.ingest("event", {"tag": ["a", "b"]})
        r.ingest("event", {"tag": {"nested": 1}})
        s = r.reduce()
        self.assertEqual(s.distinct_values["event.tag"], 2)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        r = osr.ObservationStreamReducer(
            distinct_axes=[
                osr.DistinctReducer("a", "b"),
            ],
        )
        r.ingest("a", {"b": 1})
        s = r.stats()
        self.assertEqual(s["buffered_events"], 1)
        self.assertIn("a.b", s["distinct_axes"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        r = osr.ObservationStreamReducer()
        r.ingest("a")
        r.ingest("b")
        self.assertEqual(r.reset(), 2)


class TestDict(unittest.TestCase):
    def test_record_serialises(self) -> None:
        rec = osr.EventRecord(kind="x", fields={"y": 1}, ts=1.0)
        self.assertEqual(rec.as_dict()["kind"], "x")

    def test_situation_serialises(self) -> None:
        r = osr.ObservationStreamReducer()
        r.ingest("a")
        s = r.reduce()
        d = s.as_dict()
        self.assertIn("event_counts", d)


if __name__ == "__main__":
    unittest.main()
