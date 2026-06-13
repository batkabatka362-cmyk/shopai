"""Tests for engines.cold_start_orchestrator — W963-14."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.cold_start_orchestrator import (
    ColdStartOrchestratorEngine,
)


# ── Pattern Q envelope ─────────────────────────────────────


class TestEnvelope:
    def test_empty_input_returns_success(self):
        result = ColdStartOrchestratorEngine().run({})
        # Empty -> defaults niche=general, runs the chain.
        assert result["status"] == "success"

    def test_none_input_success(self):
        result = ColdStartOrchestratorEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_error(self):
        result = ColdStartOrchestratorEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = ColdStartOrchestratorEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"


# ── Step composition ──────────────────────────────────────


class TestSteps:
    def test_steps_dict_includes_all_phases(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "beauty"},
        })
        steps = result["data"]["steps"]
        assert "diagnose" in steps
        assert "blog_seed" in steps
        assert "cro" in steps
        assert "channels" in steps
        assert "earnings" in steps

    def test_product_seed_only_when_missing(self):
        """When revenue_readiness reports has_products=ready,
        product_seed step should be skipped."""
        # Patch the diagnostic to return a non-cold-start state.
        with patch(
            "engines.cold_start_orchestrator.flow."
            "ColdStartOrchestratorEngine._step_diagnose",
            return_value={
                "ok": True,
                "verdict": "growing",
                "gates_passed": 4,
                "gates_total": 6,
                "has_products_status": "ready",
                "next_action": "",
            },
        ):
            result = ColdStartOrchestratorEngine().run({
                "data": {"niche": "beauty"},
            })
        steps = result["data"]["steps"]
        assert "product_seed" not in steps

    def test_earning_active_short_circuits(self):
        """When already earning, orchestrator returns early
        with no actions."""
        with patch(
            "engines.cold_start_orchestrator.flow."
            "ColdStartOrchestratorEngine._step_diagnose",
            return_value={
                "ok": True,
                "verdict": "earning_active",
                "gates_passed": 6,
                "gates_total": 6,
                "has_products_status": "ready",
                "next_action": "",
            },
        ):
            result = ColdStartOrchestratorEngine().run({
                "data": {"niche": "beauty"},
            })
        actions = result["data"]["next_actions"]
        assert len(actions) == 1
        assert "Already earning" in actions[0]


# ── Niche handling ────────────────────────────────────────


class TestNiche:
    def test_default_niche_is_general(self):
        result = ColdStartOrchestratorEngine().run({})
        assert result["data"]["niche"] == "general"

    def test_niche_lowercased(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "BEAUTY"},
        })
        assert result["data"]["niche"] == "beauty"

    def test_unknown_niche_skips_cro_preview(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "automotive"},
        })
        cro = result["data"]["steps"]["cro"]
        assert cro["ok"] is False


# ── Channel readiness ────────────────────────────────────


class TestChannelReadiness:
    def test_all_unconfigured(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "beauty"},
        })
        ch = result["data"]["steps"]["channels"]
        # On a clean machine none of these are wired.
        assert ch["ads_ready"] is False
        assert ch["pinterest_ready"] is False
        # Email + TikTok + Instagram same
        assert "email_ready" in ch
        assert "tiktok_ready" in ch
        # W963-99: Instagram channel check added
        assert "instagram_ready" in ch
        assert ch["instagram_ready"] is False

    def test_instagram_next_action_when_unconfigured(self):
        """W963-99 regression: cold-start was missing the
        Instagram channel-readiness surface. Now operator
        sees the fix hint in next_actions when not
        configured."""
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "beauty"},
        })
        actions = result["data"]["next_actions"]
        assert any(
            "INSTAGRAM_ACCESS_TOKEN" in a for a in actions
        )


# ── Apply mode ────────────────────────────────────────────


class TestApplyMode:
    def test_preview_mode_includes_next_action_for_seed(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {"niche": "beauty"},
        })
        actions = result["data"]["next_actions"]
        # Preview should suggest --yes commands.
        assert any(
            "blog-candidates" in a for a in actions
        )

    def test_apply_mode_records(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {
                "niche": "beauty",
                "apply": True,
            },
        })
        assert result["data"]["apply_mode"] is True


# ── End-to-end with store_id ──────────────────────────────


class TestEndToEnd:
    def test_with_store_id_diagnostic_passes_through(self):
        result = ColdStartOrchestratorEngine().run({
            "data": {
                "store_id": "main",
                "niche": "beauty",
            },
        })
        assert result["data"]["store_id"] == "main"
