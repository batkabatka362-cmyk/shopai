"""Bias detector tests."""
from __future__ import annotations

import unittest

from core.brain import bias_detector as bd


class TestMeasureUniform(unittest.TestCase):
    def test_uniform_expected_split(self) -> None:
        records = [
            {"niche": "audio"}, {"niche": "audio"},
            {"niche": "fashion"}, {"niche": "home"},
        ]
        report = bd.measure(records, "niche")
        self.assertEqual(report.total, 4)
        # 3 distinct values → expected = 1/3 each
        for s in report.slices:
            self.assertAlmostEqual(s.expected, 1 / 3, places=2)

    def test_single_value_full_share(self) -> None:
        report = bd.measure([{"x": "a"}, {"x": "a"}], "x")
        self.assertEqual(len(report.slices), 1)
        self.assertEqual(report.slices[0].share, 1.0)
        # only 1 value → expected = 1.0 → disparity = 0
        self.assertEqual(report.slices[0].disparity, 0.0)


class TestBaseline(unittest.TestCase):
    def test_custom_baseline_applied(self) -> None:
        records = [{"n": "a"}] * 9 + [{"n": "b"}]
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "n", baseline=baseline)
        slice_a = next(s for s in report.slices if s.value == "a")
        self.assertAlmostEqual(slice_a.share, 0.9)
        self.assertAlmostEqual(slice_a.expected, 0.5)
        self.assertAlmostEqual(slice_a.disparity, 0.4)

    def test_baseline_keys_without_observations(self) -> None:
        # 'c' is in baseline but never observed — still reported as a
        # negative disparity slice.
        records = [{"n": "a"}, {"n": "b"}]
        baseline = {"a": 0.3, "b": 0.3, "c": 0.4}
        report = bd.measure(records, "n", baseline=baseline)
        values = {s.value for s in report.slices}
        self.assertIn("c", values)
        slice_c = next(s for s in report.slices if s.value == "c")
        self.assertEqual(slice_c.sample_size, 0)
        self.assertLess(slice_c.disparity, 0)


class TestSeverity(unittest.TestCase):
    def test_high_severity_over_20pct(self) -> None:
        # a occurs in 9/10 → share 0.9, expected 0.5 → disparity 0.4
        records = [{"x": "a"}] * 9 + [{"x": "b"}]
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "x", baseline=baseline)
        slice_a = next(s for s in report.slices if s.value == "a")
        self.assertEqual(slice_a.severity, "high")

    def test_medium_severity(self) -> None:
        # disparity ≈ 0.12 → medium
        records = [{"x": "a"}] * 62 + [{"x": "b"}] * 38
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "x", baseline=baseline)
        slice_a = next(s for s in report.slices if s.value == "a")
        self.assertEqual(slice_a.severity, "medium")

    def test_low_severity(self) -> None:
        records = [{"x": "a"}] * 52 + [{"x": "b"}] * 48
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "x", baseline=baseline)
        slice_a = next(s for s in report.slices if s.value == "a")
        self.assertEqual(slice_a.severity, "low")


class TestEmpty(unittest.TestCase):
    def test_empty_records(self) -> None:
        report = bd.measure([], "x")
        self.assertEqual(report.total, 0)
        self.assertEqual(report.slices, [])

    def test_attribute_missing(self) -> None:
        # attribute present only in some records
        records = [{"x": "a"}, {"y": "b"}, {"x": "a"}]
        report = bd.measure(records, "x")
        self.assertEqual(report.total, 2)

    def test_non_dict_skipped(self) -> None:
        records = [{"x": "a"}, "not a dict", {"x": "b"}]
        report = bd.measure(records, "x")
        self.assertEqual(report.total, 2)


class TestSorting(unittest.TestCase):
    def test_worst_slice_first(self) -> None:
        records = [{"x": "a"}] * 9 + [{"x": "b"}]
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "x", baseline=baseline)
        # biggest |disparity| comes first
        first = report.slices[0]
        self.assertGreaterEqual(
            abs(first.disparity),
            abs(report.slices[-1].disparity),
        )

    def test_worst_property(self) -> None:
        records = [{"x": "a"}] * 9 + [{"x": "b"}]
        baseline = {"a": 0.5, "b": 0.5}
        report = bd.measure(records, "x", baseline=baseline)
        self.assertEqual(report.worst.value, "a")

    def test_worst_none_on_empty(self) -> None:
        report = bd.measure([], "x")
        self.assertIsNone(report.worst)


class TestAsDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        records = [{"x": "a"}, {"x": "b"}]
        d = bd.measure(records, "x").as_dict()
        self.assertIn("slices", d)
        self.assertEqual(d["total"], 2)
        self.assertEqual(d["attribute"], "x")

    def test_slice_serialises(self) -> None:
        records = [{"x": "a"}]
        d = bd.measure(records, "x").slices[0].as_dict()
        self.assertIn("share", d)
        self.assertIn("disparity", d)
        self.assertIn("severity", d)


class TestCompare(unittest.TestCase):
    def test_group_success_rates(self) -> None:
        records = [
            {"niche": "audio", "success": True},
            {"niche": "audio", "success": True},
            {"niche": "audio", "success": True},
            {"niche": "audio", "success": False},
            {"niche": "fashion", "success": False},
            {"niche": "fashion", "success": False},
            {"niche": "fashion", "success": True},
            {"niche": "fashion", "success": False},
        ]
        result = bd.compare(records, "niche")
        audio = next(g for g in result if g.group == "audio")
        fashion = next(g for g in result if g.group == "fashion")
        self.assertAlmostEqual(audio.success_rate, 0.75)
        self.assertAlmostEqual(fashion.success_rate, 0.25)

    def test_global_delta_computed(self) -> None:
        records = [
            {"g": "a", "success": True},
            {"g": "a", "success": True},
            {"g": "b", "success": False},
            {"g": "b", "success": False},
        ]
        result = bd.compare(records, "g")
        a = next(g for g in result if g.group == "a")
        # global success rate = 0.5, a = 1.0 → delta = 0.5
        self.assertAlmostEqual(a.vs_global_delta, 0.5)

    def test_empty_records(self) -> None:
        self.assertEqual(bd.compare([], "g"), [])

    def test_sort_by_abs_delta(self) -> None:
        records = [
            {"g": "a", "success": True},
            {"g": "b", "success": False},
            {"g": "c", "success": True},
            {"g": "c", "success": False},
        ]
        result = bd.compare(records, "g")
        # a (+0.5) & b (-0.5) tied; c (0) last
        self.assertEqual(result[-1].group, "c")

    def test_custom_outcome_key(self) -> None:
        records = [
            {"g": "a", "won": 1},
            {"g": "a", "won": 0},
        ]
        result = bd.compare(records, "g", outcome_key="won")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].success_rate, 0.5)


class TestGroupDict(unittest.TestCase):
    def test_group_as_dict(self) -> None:
        records = [{"g": "a", "success": True}]
        d = bd.compare(records, "g")[0].as_dict()
        self.assertIn("success_rate", d)
        self.assertIn("vs_global_delta", d)
        self.assertIn("n", d)


if __name__ == "__main__":
    unittest.main()
