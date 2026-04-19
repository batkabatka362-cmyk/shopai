"""Multi-touch attribution tests."""
from __future__ import annotations

import unittest

from core.brain import attribution as at


def _j(channels: list[str], *, value: float = 100.0,
       costs: list[float] | None = None) -> at.Journey:
    costs = costs or [0.0] * len(channels)
    touches = [
        at.Touch(channel=c, timestamp=1000.0 + i * 3600.0,
                 cost_usd=costs[i])
        for i, c in enumerate(channels)
    ]
    return at.Journey(
        journey_id="j", touches=touches,
        conversion_value=value,
    )


class TestLastClick(unittest.TestCase):
    def test_credits_final_touch(self) -> None:
        credits = at.last_click(_j(["meta", "email", "organic"]))
        self.assertEqual(credits, {"organic": 1.0})

    def test_empty_journey(self) -> None:
        self.assertEqual(at.last_click(at.Journey("x", [], 100.0)), {})


class TestFirstClick(unittest.TestCase):
    def test_credits_first_touch(self) -> None:
        credits = at.first_click(_j(["meta", "email", "organic"]))
        self.assertEqual(credits, {"meta": 1.0})


class TestLinear(unittest.TestCase):
    def test_split_equally(self) -> None:
        credits = at.linear(_j(["meta", "email"]))
        self.assertAlmostEqual(credits["meta"], 0.5)
        self.assertAlmostEqual(credits["email"], 0.5)

    def test_same_channel_doubled(self) -> None:
        credits = at.linear(_j(["meta", "meta", "organic"]))
        self.assertAlmostEqual(credits["meta"], 2 / 3)
        self.assertAlmostEqual(credits["organic"], 1 / 3)


class TestTimeDecay(unittest.TestCase):
    def test_newer_weighted_higher(self) -> None:
        credits = at.time_decay(_j(["meta", "email"]),
                                 half_life_hours=1.0)
        # email is more recent → higher weight
        self.assertGreater(credits["email"], credits["meta"])

    def test_sums_to_one(self) -> None:
        credits = at.time_decay(_j(["a", "b", "c"]))
        self.assertAlmostEqual(sum(credits.values()), 1.0)


class TestPositionBased(unittest.TestCase):
    def test_40_40_20_split(self) -> None:
        credits = at.position_based(_j(["a", "b", "c", "d"]))
        self.assertAlmostEqual(credits["a"], 0.4)
        self.assertAlmostEqual(credits["d"], 0.4)
        # middle share = 0.2 split across b + c
        self.assertAlmostEqual(credits["b"], 0.1)
        self.assertAlmostEqual(credits["c"], 0.1)

    def test_two_touches_split_evenly(self) -> None:
        credits = at.position_based(_j(["a", "b"]))
        self.assertAlmostEqual(credits["a"], 0.5)
        self.assertAlmostEqual(credits["b"], 0.5)


class TestShapley(unittest.TestCase):
    def test_single_channel_gets_all(self) -> None:
        credits = at.shapley(_j(["meta"]))
        self.assertEqual(credits, {"meta": 1.0})

    def test_two_channels_last_click_higher(self) -> None:
        # last_channel is always included in coalitions that convert
        # at value 1, so it should get strictly more credit.
        credits = at.shapley(_j(["meta", "email"]))
        self.assertGreater(credits["email"], credits["meta"])

    def test_falls_back_when_too_many_channels(self) -> None:
        # 7+ unique channels exceeds exponential cap
        channels = [f"ch{i}" for i in range(7)]
        credits = at.shapley(_j(channels))
        self.assertAlmostEqual(sum(credits.values()), 1.0, places=3)

    def test_sums_to_one(self) -> None:
        credits = at.shapley(_j(["meta", "email", "organic"]))
        self.assertAlmostEqual(sum(credits.values()), 1.0, places=3)


class TestAggregate(unittest.TestCase):
    def test_reports_revenue_and_spend(self) -> None:
        journeys = [
            _j(["meta", "email"], value=100.0, costs=[10, 2]),
            _j(["meta", "organic"], value=200.0, costs=[10, 0]),
        ]
        reports = at.aggregate(journeys, model="linear")
        self.assertIn("meta", reports)
        self.assertIn("email", reports)
        self.assertAlmostEqual(reports["meta"].credited_revenue,
                                50 + 100)
        self.assertAlmostEqual(reports["meta"].spend, 20.0)

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(ValueError):
            at.aggregate([], model="bogus")

    def test_unconverted_journey_skipped_for_revenue(self) -> None:
        j = _j(["meta"], value=100, costs=[5])
        j.converted = False
        reports = at.aggregate([j], model="linear")
        self.assertEqual(reports["meta"].credited_revenue, 0)
        self.assertEqual(reports["meta"].spend, 5)


class TestChannelReport(unittest.TestCase):
    def test_roas_computed(self) -> None:
        r = at.ChannelReport(channel="meta",
                              credited_revenue=300, spend=100)
        self.assertAlmostEqual(r.roas, 3.0)

    def test_roas_zero_on_zero_spend(self) -> None:
        r = at.ChannelReport(channel="x",
                              credited_revenue=100, spend=0)
        self.assertEqual(r.roas, 0.0)


if __name__ == "__main__":
    unittest.main()
