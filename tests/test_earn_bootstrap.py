"""Tests for engines.earn_bootstrap — W963-5."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.earn_bootstrap import EarnBootstrapEngine


# ── Pattern Q envelope ─────────────────────────────────────


class TestEnvelope:
    def test_empty_input_returns_success(self):
        result = EarnBootstrapEngine().run({})
        assert set(result.keys()) == {
            "status", "data", "meta", "error",
        }
        assert result["status"] == "success"
        assert result["meta"]["engine"] == "earn_bootstrap"

    def test_none_input_returns_success(self):
        result = EarnBootstrapEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_returns_error(self):
        result = EarnBootstrapEngine().run("not a dict")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = EarnBootstrapEngine().run({
            "status": "fail", "error": "upstream broke",
        })
        assert result["status"] == "error"


# ── Cold-start chain ───────────────────────────────────────


class TestColdStart:
    def test_no_niche_returns_cold_skipped(self):
        result = EarnBootstrapEngine().run({"data": {}})
        assert result["data"]["chain_verdict"] == "cold_skipped"
        assert any(
            "niche" in step.lower()
            for step in result["data"]["next_steps"]
        )

    def test_preview_mode_default(self):
        result = EarnBootstrapEngine().run({
            "data": {"niche": "beauty", "count": 5},
        })
        assert result["data"]["chain_verdict"] == "cold_pending"
        assert result["data"]["candidates_summary"]["count"] == 5
        assert result["data"]["pending_actions"] == []

    def test_apply_mode_queues(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = lambda **kw: MagicMock(
            id="appr_" + kw["params"]["title"][:8],
        )
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            result = EarnBootstrapEngine().run({
                "data": {
                    "niche": "fashion", "count": 3, "apply": True,
                },
            })
        assert result["data"]["chain_verdict"] == "cold_seeded"
        assert len(result["data"]["pending_actions"]) == 3

    def test_apply_with_queue_failure_yields_skipped(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = RuntimeError(
            "queue down",
        )
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            result = EarnBootstrapEngine().run({
                "data": {
                    "niche": "tech", "count": 2, "apply": True,
                },
            })
        assert result["data"]["chain_verdict"] == "cold_skipped"


# ── Diagnostic short-circuit ───────────────────────────────


class TestDiagnosticShortCircuit:
    def test_already_earning_returns_ready(self):
        """When revenue_readiness verdict is earning_active the
        chain should NOT seed products."""
        fake_diag = {
            "status": "success",
            "data": {
                "verdict": "earning_active",
                "passed": 6, "total": 6,
                "gates": [],
                "next_action": "",
            },
        }
        with patch(
            "engines.revenue_readiness.RevenueReadinessEngine.run",
            return_value=fake_diag,
        ):
            result = EarnBootstrapEngine().run({
                "data": {"niche": "beauty", "apply": True},
            })
        assert result["data"]["chain_verdict"] == "ready"
        assert result["data"]["pending_actions"] == []

    def test_products_exist_yields_partial(self):
        """If has_products gate is ready but other gates fail,
        bootstrap can't help directly."""
        fake_diag = {
            "status": "success",
            "data": {
                "verdict": "building_traction",
                "passed": 3, "total": 6,
                "gates": [
                    {"name": "has_products", "status": "ready"},
                    {"name": "has_orders_recent", "status": "missing"},
                ],
                "next_action": "Wire ads",
            },
        }
        with patch(
            "engines.revenue_readiness.RevenueReadinessEngine.run",
            return_value=fake_diag,
        ):
            result = EarnBootstrapEngine().run({
                "data": {"niche": "beauty"},
            })
        assert result["data"]["chain_verdict"] == "partial"


# ── Invalid inputs ──────────────────────────────────────────


class TestInvalidInputs:
    def test_unknown_niche_propagates_error_via_product_sourcer(self):
        result = EarnBootstrapEngine().run({
            "data": {"niche": "cars"},
        })
        assert result["data"]["chain_verdict"] == "cold_skipped"

    def test_zero_count_falls_back_to_default(self):
        result = EarnBootstrapEngine().run({
            "data": {"niche": "home", "count": 0},
        })
        # Default 20; 20 candidates exist in home catalog.
        assert (
            result["data"]["candidates_summary"]["count"] == 20
        )

    def test_non_int_count_falls_back_to_default(self):
        result = EarnBootstrapEngine().run({
            "data": {"niche": "food", "count": "many"},
        })
        assert (
            result["data"]["candidates_summary"]["count"] == 20
        )
