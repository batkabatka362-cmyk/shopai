"""Tests for engines.fleet_strategist — W963-35."""
from __future__ import annotations

from unittest.mock import patch

from engines.fleet_strategist import FleetStrategistEngine
from engines.fleet_strategist.ranker import (
    FleetStrategistReport,
    StoreRanking,
    _bucket_for,
    _sort_within_bucket,
    overall_verdict,
    rank_fleet,
)


# ── _bucket_for ───────────────────────────────────────────


class TestBucketFor:
    def test_intervene_with_revenue(self):
        assert _bucket_for("intervene", 100.0, 3) == "intervene_now"

    def test_intervene_zero_revenue_goes_to_cold(self):
        assert _bucket_for("intervene", 0.0, 2) == "cold_start"

    def test_active_bucket(self):
        assert _bucket_for("active", 500.0, 2) == "active"

    def test_zero_revenue_few_recs_cold_start(self):
        assert _bucket_for("wait", 0.0, 2) == "cold_start"

    def test_zero_revenue_many_recs_quiet(self):
        # >3 recommendations + zero revenue → quiet (not cold)
        assert _bucket_for("wait", 0.0, 10) == "quiet"


# ── _sort_within_bucket ───────────────────────────────────


class TestSortWithinBucket:
    def test_sorted_by_priority_desc(self):
        a = StoreRanking(
            store_id="a", fleet_priority=0.3,
            urgency_score=0.5,
        )
        b = StoreRanking(
            store_id="b", fleet_priority=0.8,
            urgency_score=0.6,
        )
        c = StoreRanking(
            store_id="c", fleet_priority=0.5,
            urgency_score=0.4,
        )
        out = _sort_within_bucket([a, b, c])
        assert [r.store_id for r in out] == ["b", "c", "a"]

    def test_ties_broken_by_urgency(self):
        a = StoreRanking(
            store_id="a", fleet_priority=0.5,
            urgency_score=0.3,
        )
        b = StoreRanking(
            store_id="b", fleet_priority=0.5,
            urgency_score=0.7,
        )
        out = _sort_within_bucket([a, b])
        assert out[0].store_id == "b"

    def test_empty(self):
        assert _sort_within_bucket([]) == []


# ── rank_fleet ────────────────────────────────────────────


def _fake_strategist_result(
    store_id="s1",
    verdict="wait",
    revenue=0.0,
    rec_count=2,
    top_action="x",
    top_drill="shopai x",
    priority=0.4,
):
    return {
        "status": "success",
        "data": {
            "store_id": store_id,
            "niche": "beauty",
            "verdict": verdict,
            "context": {"total_revenue_7d": revenue},
            "recommendations": (
                [
                    {
                        "action": top_action,
                        "drill_command": top_drill,
                        "confidence": 0.8,
                        "impact": "high",
                        "reasoning": "...",
                        "priority_score": priority,
                    },
                ]
                + [
                    {
                        "action": f"rec{i}",
                        "drill_command": "x",
                        "confidence": 0.5,
                        "impact": "low",
                        "reasoning": "...",
                        "priority_score": 0.2,
                    }
                    for i in range(rec_count - 1)
                ]
            ) if rec_count else [],
        },
        "meta": {}, "error": None,
    }


class TestRankFleet:
    def test_empty_fleet(self):
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=[],
        ):
            r = rank_fleet()
        assert r.total_stores == 0
        assert r.stores_with_data == 0

    def test_iterates_stores(self):
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.return_value = (
                _fake_strategist_result()
            )
            r = rank_fleet()
        assert r.total_stores == 3
        assert r.stores_with_data == 3

    def test_verdict_filter(self):
        def _multi(payload):
            sid = payload["data"]["store_id"]
            verdict = (
                "intervene" if sid == "s2" else "wait"
            )
            return _fake_strategist_result(
                store_id=sid, verdict=verdict, revenue=100,
            )
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.side_effect = _multi
            r = rank_fleet(verdict_filter="intervene")
        assert r.stores_with_data == 1
        assert r.all_rankings[0].store_id == "s2"

    def test_top_filter(self):
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.return_value = (
                _fake_strategist_result(revenue=100)
            )
            r = rank_fleet(top=2)
        assert len(r.all_rankings) == 2

    def test_per_store_exception_isolated(self):
        # Resilience: chaos-style scenario where one store
        # raises but others succeed.
        call_count = {"n": 0}
        def _flaky(payload):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("store 2 broke")
            return _fake_strategist_result(
                store_id=payload["data"]["store_id"],
            )
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.side_effect = _flaky
            r = rank_fleet()
        # s2 dropped, s1 + s3 remain
        ids = [r.store_id for r in r.all_rankings]
        assert "s2" not in ids

    def test_intervene_bucket_separates_high_revenue(self):
        def _multi(payload):
            sid = payload["data"]["store_id"]
            if sid == "s2":
                return _fake_strategist_result(
                    store_id="s2",
                    verdict="intervene",
                    revenue=500,
                )
            return _fake_strategist_result(
                store_id=sid, verdict="wait", revenue=0,
            )
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.side_effect = _multi
            r = rank_fleet()
        assert len(r.by_bucket["intervene_now"]) == 1
        assert (
            r.by_bucket["intervene_now"][0].store_id == "s2"
        )

    def test_revenue_weight_log_smooths(self):
        # Big difference in revenue should NOT translate to
        # equally big difference in fleet_priority (log scale).
        def _two_revenues(payload):
            sid = payload["data"]["store_id"]
            return _fake_strategist_result(
                store_id=sid,
                verdict="wait",
                revenue=100 if sid == "s1" else 10000,
                priority=0.5,
            )
        with patch(
            "engines.fleet_strategist.ranker._list_fleet_stores",
            return_value=["s1", "s2"],
        ), patch(
            "engines.store_strategist.StoreStrategistEngine"
        ) as MockEng:
            MockEng.return_value.run.side_effect = _two_revenues
            r = rank_fleet()
        small = next(
            x for x in r.all_rankings if x.store_id == "s1"
        )
        big = next(
            x for x in r.all_rankings if x.store_id == "s2"
        )
        # 100x revenue ratio but only ~2x priority ratio
        assert big.fleet_priority < small.fleet_priority * 3


# ── overall_verdict ───────────────────────────────────────


class TestOverallVerdict:
    def test_no_data(self):
        r = FleetStrategistReport()
        assert overall_verdict(r) == "no_data"

    def test_intervention_needed(self):
        r = FleetStrategistReport(
            stores_with_data=3,
            by_bucket={
                "intervene_now": [
                    StoreRanking(store_id="x")
                ],
                "cold_start": [],
                "active": [],
                "quiet": [],
            },
        )
        assert overall_verdict(r) == "intervention_needed"

    def test_cold_start_fleet(self):
        r = FleetStrategistReport(
            stores_with_data=3,
            by_bucket={
                "intervene_now": [],
                "cold_start": [
                    StoreRanking(store_id="x")
                ],
                "active": [],
                "quiet": [],
            },
        )
        assert overall_verdict(r) == "cold_start_fleet"

    def test_earning_fleet_when_half_active(self):
        r = FleetStrategistReport(
            stores_with_data=4,
            by_bucket={
                "intervene_now": [],
                "cold_start": [],
                "active": [
                    StoreRanking(store_id="x"),
                    StoreRanking(store_id="y"),
                ],
                "quiet": [],
            },
        )
        assert overall_verdict(r) == "earning_fleet"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetStrategistEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetStrategistEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetStrategistEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetStrategistEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetStrategistEngine().run({})
        assert r["meta"]["engine"] == "fleet_strategist"


class TestEngineActions:
    def test_top_threaded(self):
        r = FleetStrategistEngine().run({
            "data": {"top": 3},
        })
        assert r["data"]["top_filter"] == 3

    def test_verdict_filter_threaded(self):
        r = FleetStrategistEngine().run({
            "data": {"verdict": "intervene"},
        })
        assert r["data"]["verdict_filter"] == "intervene"

    def test_invalid_top_falls_back(self):
        r = FleetStrategistEngine().run({
            "data": {"top": "abc"},
        })
        assert r["data"]["top_filter"] == 0

    def test_top_negative_floor(self):
        r = FleetStrategistEngine().run({
            "data": {"top": -5},
        })
        assert r["data"]["top_filter"] == 0
