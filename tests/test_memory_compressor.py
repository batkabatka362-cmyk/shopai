"""Memory compressor tests."""
from __future__ import annotations

import unittest

from core.memory import memory_compressor as mc


def _row(i, niche="audio", price=25.0, revenue=30.0):
    return {
        "id": f"r{i}", "niche": niche,
        "price_band": "mid",
        "price": price, "revenue": revenue,
        "ts": 1000.0 + i,
    }


class TestCompress(unittest.TestCase):
    def test_empty_rows_empty_summaries(self) -> None:
        self.assertEqual(
            mc.compress([], ["niche"]), [],
        )

    def test_below_min_group_skipped(self) -> None:
        rows = [_row(i) for i in range(5)]
        summaries = mc.compress(
            rows, ["niche"], min_group=20,
        )
        self.assertEqual(summaries, [])

    def test_single_group_summarises(self) -> None:
        rows = [_row(i) for i in range(30)]
        summaries = mc.compress(rows, ["niche"], min_group=20)
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.n_rows, 30)
        self.assertEqual(s.group_key["niche"], "audio")

    def test_numeric_stats_computed(self) -> None:
        rows = [_row(i, price=i * 1.0) for i in range(30)]
        summaries = mc.compress(rows, ["niche"], min_group=20)
        s = summaries[0]
        self.assertIn("price", s.numeric_fields)
        self.assertEqual(s.numeric_fields["price"].n, 30)
        self.assertEqual(s.numeric_fields["price"].min, 0.0)
        self.assertEqual(s.numeric_fields["price"].max, 29.0)

    def test_categorical_fields_counted(self) -> None:
        rows = []
        for i in range(30):
            rows.append({
                "id": f"r{i}", "niche": "audio",
                "price_band": "mid",
                "copy_tone": "luxury" if i < 20 else "friendly",
            })
        summaries = mc.compress(rows, ["niche"], min_group=20)
        s = summaries[0]
        tone = s.categorical_fields.get("copy_tone", {})
        self.assertEqual(tone["luxury"], 20)
        self.assertEqual(tone["friendly"], 10)

    def test_time_range_captured(self) -> None:
        rows = [_row(i) for i in range(30)]
        summaries = mc.compress(rows, ["niche"], min_group=20)
        s = summaries[0]
        self.assertIsNotNone(s.time_range)
        self.assertEqual(s.time_range[0], 1000.0)
        self.assertEqual(s.time_range[1], 1029.0)

    def test_multiple_groups_returned_sorted(self) -> None:
        rows = (
            [_row(i, niche="audio") for i in range(30)]
            + [_row(i, niche="fashion") for i in range(50)]
        )
        summaries = mc.compress(rows, ["niche"], min_group=20)
        self.assertEqual(len(summaries), 2)
        self.assertGreaterEqual(summaries[0].n_rows, summaries[1].n_rows)

    def test_sample_ids_truncated(self) -> None:
        rows = [_row(i) for i in range(30)]
        summaries = mc.compress(
            rows, ["niche"], min_group=20, sample_limit=3,
        )
        self.assertEqual(len(summaries[0].sample_ids), 3)


class TestSignature(unittest.TestCase):
    def test_signature_stable(self) -> None:
        a = mc._signature({"niche": "audio", "band": "mid"})
        b = mc._signature({"band": "mid", "niche": "audio"})
        self.assertEqual(a, b)

    def test_signature_differs_on_value(self) -> None:
        a = mc._signature({"niche": "audio"})
        b = mc._signature({"niche": "fashion"})
        self.assertNotEqual(a, b)


class TestRehydrate(unittest.TestCase):
    def test_rehydrate_finds_matching_row(self) -> None:
        rows = [_row(i) for i in range(30)]
        summaries = mc.compress(rows, ["niche"], min_group=20)
        hydrated = mc.rehydrate(summaries[0], "r5", rows)
        self.assertIsNotNone(hydrated)
        self.assertEqual(hydrated["id"], "r5")

    def test_rehydrate_unknown_id_none(self) -> None:
        rows = [_row(i) for i in range(30)]
        summaries = mc.compress(rows, ["niche"], min_group=20)
        self.assertIsNone(
            mc.rehydrate(summaries[0], "missing", rows),
        )


class TestNumericStats(unittest.TestCase):
    def test_stats_as_dict(self) -> None:
        s = mc.NumericStats(n=3, min=1, max=3, mean=2, stdev=1.0)
        d = s.as_dict()
        self.assertEqual(d["n"], 3)

    def test_empty_stats(self) -> None:
        s = mc.NumericStats()
        self.assertIsNone(s.as_dict()["min"])


if __name__ == "__main__":
    unittest.main()
