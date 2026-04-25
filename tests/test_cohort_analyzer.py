"""Cohort analyzer tests."""
from __future__ import annotations

import datetime as dt
import unittest

from core.brain import cohort_analyzer as ca


def _ts(y, m, d=1):
    return dt.datetime(y, m, d).timestamp()


def _rec(cid, y, m, d=1, hint=""):
    return ca.OrderRecord(
        customer_id=cid, order_ts=_ts(y, m, d), cohort_hint=hint,
    )


class TestBuild(unittest.TestCase):
    def test_simple_cohort_month_assigned(self) -> None:
        records = [
            _rec("c1", 2024, 3), _rec("c1", 2024, 4),
            _rec("c2", 2024, 3),
        ]
        grid = ca.build(records, max_months=3)
        self.assertIn("2024-03", grid.cohorts)

    def test_retention_month_0_is_100_percent(self) -> None:
        records = [
            _rec("c1", 2024, 3),
            _rec("c2", 2024, 3),
        ]
        grid = ca.build(records)
        self.assertEqual(grid.retention("2024-03", 0), 1.0)

    def test_retention_decays(self) -> None:
        # 3 customers in 2024-01; 2 return in month 1, 1 in month 3
        records = [
            _rec("c1", 2024, 1), _rec("c1", 2024, 2), _rec("c1", 2024, 4),
            _rec("c2", 2024, 1), _rec("c2", 2024, 2),
            _rec("c3", 2024, 1),
        ]
        grid = ca.build(records, max_months=6)
        self.assertAlmostEqual(
            grid.retention("2024-01", 1), 2 / 3, places=3,
        )
        self.assertAlmostEqual(
            grid.retention("2024-01", 3), 1 / 3, places=3,
        )

    def test_dict_records_accepted(self) -> None:
        recs = [{
            "customer_id": "x",
            "order_ts": _ts(2024, 2),
            "cohort_hint": "",
        }]
        grid = ca.build(recs)
        self.assertIn("2024-02", grid.cohorts)

    def test_custom_cohort_key(self) -> None:
        records = [
            ca.OrderRecord("c1", _ts(2024, 1), cohort_hint="meta"),
            ca.OrderRecord("c2", _ts(2024, 3), cohort_hint="organic"),
        ]
        grid = ca.build(
            records,
            cohort_key=lambda r: r.cohort_hint,
        )
        self.assertIn("meta", grid.cohorts)
        self.assertIn("organic", grid.cohorts)

    def test_invalid_records_dropped(self) -> None:
        records = [
            ca.OrderRecord("", _ts(2024, 1)),         # no id
            ca.OrderRecord("c1", 0),                    # no ts
        ]
        grid = ca.build(records)
        self.assertEqual(grid.cohorts, [])


class TestRetention(unittest.TestCase):
    def test_unknown_cohort_zero(self) -> None:
        grid = ca.build([])
        self.assertEqual(grid.retention("2020-01", 3), 0.0)

    def test_cohort_size(self) -> None:
        records = [
            _rec("a", 2024, 1), _rec("b", 2024, 1), _rec("c", 2024, 1),
        ]
        grid = ca.build(records)
        self.assertEqual(grid.cohort_size("2024-01"), 3)

    def test_cohort_size_unknown_zero(self) -> None:
        grid = ca.build([])
        self.assertEqual(grid.cohort_size("1999-01"), 0)


class TestCompare(unittest.TestCase):
    def test_compare_delta(self) -> None:
        records = [
            _rec("a", 2024, 1), _rec("a", 2024, 2),
            _rec("b", 2024, 1),
            _rec("c", 2024, 3),
        ]
        grid = ca.build(records, max_months=3)
        delta = ca.compare(grid, "2024-01", "2024-03", at_month=0)
        # Both at month 0 = 100% retention
        self.assertAlmostEqual(delta, 0.0)


class TestBestWorst(unittest.TestCase):
    def test_picks_best_and_worst(self) -> None:
        # Four customers in 2024-01 (all return month 1),
        # four customers in 2024-03 (none return).
        records = []
        for i in range(4):
            records.append(_rec(f"a{i}", 2024, 1))
            records.append(_rec(f"a{i}", 2024, 2))
            records.append(_rec(f"b{i}", 2024, 3))
        grid = ca.build(records, max_months=3)
        best, worst = ca.best_and_worst(grid, at_month=1,
                                          min_cohort_size=3)
        self.assertEqual(best[0], "2024-01")
        self.assertEqual(worst[0], "2024-03")

    def test_min_size_filter_excludes_tiny(self) -> None:
        records = [_rec("lone", 2024, 1)]
        grid = ca.build(records)
        best, worst = ca.best_and_worst(
            grid, at_month=0, min_cohort_size=5,
        )
        self.assertIsNone(best)
        self.assertIsNone(worst)


class TestAverageCurve(unittest.TestCase):
    def test_average_curve_shape(self) -> None:
        records = [
            _rec("a", 2024, 1), _rec("a", 2024, 2),
            _rec("b", 2024, 1), _rec("b", 2024, 2),
            _rec("c", 2024, 1),
        ]
        grid = ca.build(records, max_months=3)
        curve = ca.average_curve(grid, min_cohort_size=1)
        # Month 0 = 100%
        self.assertAlmostEqual(curve[0][1], 1.0)
        # Month 1 = 2/3
        self.assertAlmostEqual(curve[1][1], 2 / 3, places=3)


if __name__ == "__main__":
    unittest.main()
