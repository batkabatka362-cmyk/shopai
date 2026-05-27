"""Tests for engines.store_setup.onboarding_wizard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.store_setup.onboarding_wizard import (
    OnboardingResult,
    OnboardingStage,
    onboard_store,
)


def _fake_sm():
    """Minimal StoreManager stub that succeeds at every stage."""
    sm = MagicMock()
    sm.add_store.return_value = {
        "store_id": "s1", "status": "added",
    }
    sm.update_store_niche.return_value = {
        "store_id": "s1", "niche": "beauty", "status": "updated",
    }
    sm.get_store.return_value = {
        "store_id": "s1", "niche": "beauty",
    }
    sm.get_products.return_value = []
    return sm


class TestValidation:

    def test_missing_store_id_fails_fast(self):
        r = onboard_store(
            store_id="", shop_url="x.myshopify.com",
            api_key="t",
        )
        assert r.final_verdict == "failed"
        assert r.stages[0].name == "validation"
        assert "store_id" in r.stages[0].detail

    def test_missing_shop_url_fails_fast(self):
        r = onboard_store(
            store_id="s1", shop_url="",
            api_key="t",
        )
        assert r.final_verdict == "failed"
        assert "shop_url" in r.stages[0].detail

    def test_missing_credentials_fails_fast(self):
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
        )
        assert r.final_verdict == "failed"
        assert "credentials" in r.stages[0].detail

    def test_oauth_credentials_satisfies_validation(self):
        sm = _fake_sm()
        # Add store succeeds; later stages do best-effort
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            client_id="cid", client_secret="cs",
            store_manager=sm,
        )
        # No validation stage in the stages list when valid
        assert r.stages[0].name != "validation"


class TestDryRun:

    def test_dry_run_returns_plan_without_writing(self):
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", dry_run=True,
        )
        assert r.final_verdict == "dry_run"
        # All 6 stages surfaced as skipped
        stage_names = [s.name for s in r.stages]
        assert "register" in stage_names
        assert "sync" in stage_names
        assert "niche_detect" in stage_names
        assert "launch" in stage_names
        assert "go_live" in stage_names
        assert "schedule" in stage_names
        # Every dry-run stage is "skipped"
        assert all(s.status == "skipped" for s in r.stages)

    def test_dry_run_does_not_call_store_manager(self):
        sm = MagicMock()
        onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", dry_run=True, store_manager=sm,
        )
        sm.add_store.assert_not_called()


class TestRegisterStage:

    def test_register_success(self):
        sm = _fake_sm()
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        reg = next(s for s in r.stages if s.name == "register")
        assert reg.status == "success"
        sm.add_store.assert_called_once()

    def test_register_failure_aborts_chain(self):
        sm = MagicMock()
        sm.add_store.return_value = {"error": "duplicate id"}
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        assert r.final_verdict == "failed"
        # Only the register stage runs; chain aborts on fail
        assert r.stages[-1].name == "register"
        assert r.stages[-1].status == "fail"

    def test_register_exception_aborts_chain(self):
        sm = MagicMock()
        sm.add_store.side_effect = RuntimeError("db down")
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        assert r.final_verdict == "failed"
        assert "db down" in r.stages[-1].detail


class TestNicheStage:

    def test_operator_niche_skips_detection(self):
        sm = _fake_sm()
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", niche="beauty", store_manager=sm,
        )
        nd = next(
            s for s in r.stages if s.name == "niche_detect"
        )
        assert nd.status == "skipped"
        assert "operator-supplied" in nd.detail

    def test_high_confidence_detection_auto_applies(self):
        sm = _fake_sm()
        # Catalog matches beauty cleanly
        sm.get_products.return_value = [
            {"title": "Lipstick", "tags": ["makeup"]},
            {"title": "Foundation", "tags": ["cosmetics"]},
            {"title": "Serum", "tags": ["skincare"]},
            {"title": "Moisturizer", "tags": ["beauty"]},
        ]
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        nd = next(
            s for s in r.stages if s.name == "niche_detect"
        )
        # detector returns high confidence -> auto-apply
        assert nd.status == "success"
        assert nd.data.get("niche") == "beauty"
        assert nd.data.get("source") == "detector"
        sm.update_store_niche.assert_called_with(
            "s1", "beauty",
        )

    def test_low_confidence_does_not_auto_apply(self):
        sm = _fake_sm()
        # No keywords -> no_data confidence
        sm.get_products.return_value = [
            {"title": "Generic Item"},
            {"title": "Whatever"},
        ]
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        nd = next(
            s for s in r.stages if s.name == "niche_detect"
        )
        assert nd.status == "warn"
        # update_store_niche was NOT called for low confidence
        sm.update_store_niche.assert_not_called()


class TestFinalVerdict:

    def test_clean_chain_verdict_ready(self):
        sm = _fake_sm()
        # Force beauty catalog -> high confidence detection
        sm.get_products.return_value = [
            {"title": "Lipstick", "tags": ["makeup"]},
            {"title": "Foundation", "tags": ["cosmetics"]},
            {"title": "Serum", "tags": ["skincare"]},
            {"title": "Moisturizer", "tags": ["beauty"]},
        ]
        # Patch downstream stages to succeed
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value={
                "ready_to_launch": True,
                "checklist": [
                    {"step": "policies", "ok": True},
                ],
            },
        ), patch(
            "engines._go_live_check.run_go_live_check",
            return_value=[],
        ), patch(
            "engines._go_live_check.summarize",
            return_value={
                "verdict": "ready_to_go_live",
                "pass": 9, "warn": 0, "fail": 0, "total": 9,
            },
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.sync_store.return_value = {
                "products": 4, "orders": 0,
            }
            r = onboard_store(
                store_id="s1", shop_url="x.myshopify.com",
                api_key="t", store_manager=sm,
            )
        assert r.final_verdict == "ready"
        assert not r.has_failures
        assert not r.has_warnings

    def test_verdict_ready_with_warnings_when_any_warn(self):
        sm = _fake_sm()
        # No catalog -> niche stage warns
        sm.get_products.return_value = []
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value={
                "ready_to_launch": True,
                "checklist": [],
            },
        ), patch(
            "engines._go_live_check.run_go_live_check",
            return_value=[],
        ), patch(
            "engines._go_live_check.summarize",
            return_value={
                "verdict": "ready_to_go_live",
                "pass": 9, "warn": 0, "fail": 0, "total": 9,
            },
        ):
            r = onboard_store(
                store_id="s1", shop_url="x.myshopify.com",
                api_key="t", store_manager=sm,
            )
        # Niche stage warns; verdict reflects that
        assert r.final_verdict == "ready_with_warnings"

    def test_schedule_stage_always_emits_cron(self):
        sm = _fake_sm()
        r = onboard_store(
            store_id="s1", shop_url="x.myshopify.com",
            api_key="t", store_manager=sm,
        )
        sched = next(
            s for s in r.stages if s.name == "schedule"
        )
        assert sched.status == "success"
        assert "shopai cycle run" in sched.data["cron_line"]
