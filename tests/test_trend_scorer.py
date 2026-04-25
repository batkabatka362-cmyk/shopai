"""Tests for agents.research.trend_scorer."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.research.trend_scorer import make_google_trends_scorer


def _trend(keyword: str, geo: str = "US"):
    t = MagicMock()
    t.keyword = keyword
    t.geo = geo
    return t


class TestGoogleTrendsScorer(unittest.TestCase):
    def test_zero_when_no_tokens(self):
        adapter = MagicMock()
        adapter.top_searches.return_value = [_trend("pet feeder")]
        score = make_google_trends_scorer(adapter)
        self.assertEqual(score("pet", ()), 0.0)

    def test_zero_when_adapter_empty(self):
        adapter = MagicMock()
        adapter.top_searches.return_value = []
        score = make_google_trends_scorer(adapter)
        self.assertEqual(score("pet", ("pet", "dog")), 0.0)

    def test_ratio_of_token_matches(self):
        adapter = MagicMock()
        adapter.top_searches.return_value = [
            _trend("pet feeder"),
            _trend("pet costume"),
            _trend("kitchen blender"),
            _trend("yoga mat"),
        ]
        score = make_google_trends_scorer(adapter)
        # 2 of 4 match "pet"
        self.assertAlmostEqual(
            score("pet", ("pet",)), 0.5,
        )

    def test_case_insensitive(self):
        adapter = MagicMock()
        adapter.top_searches.return_value = [
            _trend("PET FEEDER"),
        ]
        score = make_google_trends_scorer(adapter)
        self.assertAlmostEqual(
            score("pet", ("pet",)), 1.0,
        )

    def test_adapter_error_returns_zero(self):
        adapter = MagicMock()
        adapter.top_searches.side_effect = RuntimeError("boom")
        score = make_google_trends_scorer(adapter)
        self.assertEqual(score("pet", ("pet",)), 0.0)

    def test_eu_weight_blends_geos(self):
        adapter = MagicMock()

        def _search(*, geo, limit):
            if geo == "US":
                return [
                    _trend("pet feeder"),
                    _trend("yoga mat"),
                ]
            return [
                _trend("kitchen blender"),
                _trend("candle jar"),
            ]

        adapter.top_searches.side_effect = _search
        score = make_google_trends_scorer(
            adapter, eu_weight=0.5,
        )
        # US: 1/2 = 0.5 match for "pet"
        # EU: 0/2 = 0.0
        # Blend: 0.5*0.5 + 0.5*0.0 = 0.25
        self.assertAlmostEqual(
            score("pet", ("pet",)), 0.25,
        )

    def test_eu_weight_zero_skips_eu_call(self):
        adapter = MagicMock()
        adapter.top_searches.return_value = [_trend("pet feeder")]
        score = make_google_trends_scorer(adapter)
        score("pet", ("pet",))
        # Only the US call
        self.assertEqual(
            adapter.top_searches.call_count, 1,
        )


if __name__ == "__main__":
    unittest.main()
