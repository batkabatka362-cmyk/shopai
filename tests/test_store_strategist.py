"""Tests for engines.store_strategist — W963-28."""
from __future__ import annotations

from unittest.mock import patch

from engines.store_strategist import StoreStrategistEngine
from engines.store_strategist.reasoner import (
    Recommendation,
    StoreContext,
    _compute_priority,
    _impact_to_score,
    derive_recommendations,
    overall_verdict,
)


# ── _impact_to_score / _compute_priority ──────────────────


class TestImpactScore:
    def test_high(self):
        assert _impact_to_score("high") == 1.0

    def test_medium(self):
        assert _impact_to_score("medium") == 0.6

    def test_low(self):
        assert _impact_to_score("low") == 0.3

    def test_unknown_default(self):
        assert _impact_to_score("??") == 0.5


class TestComputePriority:
    def test_simple(self):
        r = Recommendation(
            action="x", reasoning="", confidence=0.8,
            impact="high", drill_command="",
        )
        assert abs(_compute_priority(r) - 0.8) < 0.001


# ── derive_recommendations ────────────────────────────────


class TestDeriveRecommendations:
    def test_substrate_error_blocks(self):
        ctx = StoreContext(
            store_id="s1", checkup_verdict="error",
        )
        recs = derive_recommendations(ctx)
        # Top recommendation should be the substrate fix
        assert recs[0].source_signal == "checkup"
        assert "substrate" in recs[0].action.lower()

    def test_no_products_triggers_earn_bootstrap(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=False,
            total_revenue_7d=0.0,
        )
        recs = derive_recommendations(ctx)
        actions = " ".join(r.action.lower() for r in recs)
        assert "seed" in actions or "catalog" in actions

    def test_funnel_checkout_paid_drop_drills_cart_recovery(
        self,
    ):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            funnel_weakest="checkouts_completed",
            funnel_drop=0.7,
        )
        recs = derive_recommendations(ctx)
        cart_rec = [
            r for r in recs if "cart_recovery" in r.drill_command
        ]
        assert len(cart_rec) == 1
        assert cart_rec[0].impact == "high"

    def test_funnel_checkout_started_drop_drills_cro(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            funnel_weakest="checkouts_started",
            funnel_drop=0.5,
        )
        recs = derive_recommendations(ctx)
        cro_rec = [
            r for r in recs if "cro" in r.drill_command.lower()
        ]
        assert len(cro_rec) == 1

    def test_trajectory_declining_high_priority(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            trajectory_verdict="declining",
            trajectory_slope_pct=-25.0,
        )
        recs = derive_recommendations(ctx)
        decline_rec = [
            r for r in recs
            if r.source_signal == "trajectory"
        ]
        assert len(decline_rec) == 1
        assert decline_rec[0].confidence >= 0.7

    def test_trajectory_rising_with_ads_drills_budget_bump(
        self,
    ):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            has_ads_wired=True,
            trajectory_verdict="rising",
            trajectory_slope_pct=30.0,
            funnel_verdict="healthy",
        )
        recs = derive_recommendations(ctx)
        bump = [
            r for r in recs
            if "reinvest" in r.action.lower()
            or "bump" in r.action.lower()
        ]
        assert len(bump) >= 1

    def test_no_esp_drills_email_connect(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            has_esp_wired=False,
        )
        recs = derive_recommendations(ctx)
        esp = [
            r for r in recs
            if "email connect" in r.drill_command
        ]
        assert len(esp) == 1

    def test_no_ads_with_products_drills_ads(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            has_ads_wired=False,
        )
        recs = derive_recommendations(ctx)
        ads = [
            r for r in recs
            if "ads connect" in r.drill_command
        ]
        assert len(ads) == 1

    def test_autonomy_paused_surfaces_recommendation(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            autonomy_paused=["fulfillment"],
        )
        recs = derive_recommendations(ctx)
        paused = [
            r for r in recs if r.source_signal == "autonomy"
        ]
        assert len(paused) == 1
        assert "fulfillment" in paused[0].action

    def test_quiet_store_with_revenue_recommends_schedule(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            has_ads_wired=True,
            has_esp_wired=True,
            total_revenue_7d=500.0,
            funnel_verdict="healthy",
            trajectory_verdict="flat",
            checkup_verdict="ready",
        )
        recs = derive_recommendations(ctx)
        assert len(recs) >= 1
        # Catch-all path triggers schedule recommendation
        catch = [
            r for r in recs
            if "schedule" in r.drill_command
        ]
        assert len(catch) >= 1

    def test_completely_quiet_recommends_waiting(self):
        ctx = StoreContext(
            store_id="s1",
            has_products=True,
            has_ads_wired=True,
            has_esp_wired=True,
            total_revenue_7d=0.0,
            funnel_verdict="no_traffic",
            trajectory_verdict="cold_start",
            checkup_verdict="ready",
        )
        recs = derive_recommendations(ctx)
        wait = [
            r for r in recs
            if "wait" in r.action.lower()
        ]
        assert len(wait) >= 1

    def test_recommendations_sorted_by_priority(self):
        ctx = StoreContext(
            store_id="s1",
            checkup_verdict="error",
            has_products=False,
            total_revenue_7d=0.0,
            funnel_weakest="checkouts_completed",
            funnel_drop=0.7,
            has_esp_wired=False,
        )
        recs = derive_recommendations(ctx)
        for i in range(len(recs) - 1):
            assert (
                recs[i].priority_score
                >= recs[i + 1].priority_score
            )


# ── overall_verdict ───────────────────────────────────────


class TestOverallVerdict:
    def test_intervene_when_high_confidence_high_impact(self):
        ctx = StoreContext(store_id="s1")
        recs = [
            Recommendation(
                action="x", reasoning="", confidence=0.9,
                impact="high", drill_command="",
            ),
        ]
        assert overall_verdict(ctx, recs) == "intervene"

    def test_active_when_earning(self):
        ctx = StoreContext(
            store_id="s1", total_revenue_7d=500.0,
        )
        recs = [
            Recommendation(
                action="x", reasoning="", confidence=0.5,
                impact="low", drill_command="",
            ),
        ]
        assert overall_verdict(ctx, recs) == "active"

    def test_wait_when_quiet(self):
        ctx = StoreContext(store_id="s1")
        recs = [
            Recommendation(
                action="x", reasoning="", confidence=0.3,
                impact="low", drill_command="",
            ),
        ]
        assert overall_verdict(ctx, recs) == "wait"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = StoreStrategistEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = StoreStrategistEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = StoreStrategistEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = StoreStrategistEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = StoreStrategistEngine().run({})
        assert r["meta"]["engine"] == "store_strategist"


class TestEngineActions:
    def test_store_id_threaded(self):
        r = StoreStrategistEngine().run({
            "data": {"store_id": "main"},
        })
        assert r["data"]["store_id"] == "main"

    def test_top_limit_respected(self):
        # Force a context that triggers many recommendations.
        forced_ctx = StoreContext(
            store_id="s1",
            checkup_verdict="error",
            has_products=False,
            total_revenue_7d=0.0,
            funnel_weakest="checkouts_completed",
            funnel_drop=0.7,
            has_esp_wired=False,
            has_ads_wired=False,
            trajectory_verdict="declining",
            trajectory_slope_pct=-30.0,
            autonomy_paused=["x"],
        )
        with patch(
            "engines.store_strategist.flow.collect_context",
            return_value=forced_ctx,
        ):
            r = StoreStrategistEngine().run({
                "data": {"store_id": "s1", "top": 2},
            })
        assert r["data"]["recommendation_count"] == 2

    def test_recommendations_have_drill_commands(self):
        r = StoreStrategistEngine().run({})
        for rec in r["data"]["recommendations"]:
            assert rec["drill_command"]
            assert rec["action"]
            assert 0 <= rec["confidence"] <= 1

    def test_invalid_top_falls_back(self):
        r = StoreStrategistEngine().run({
            "data": {"top": "abc"},
        })
        # top=0 means no limit; non-numeric falls back to 0
        assert r["status"] == "success"

    def test_verdict_is_valid(self):
        r = StoreStrategistEngine().run({})
        assert r["data"]["verdict"] in {
            "intervene", "active", "wait",
        }
