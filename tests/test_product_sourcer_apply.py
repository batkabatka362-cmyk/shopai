"""W963-3: tests for product_sourcer --apply / draft_creator path."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.product_sourcer import ProductSourcerEngine
from engines.product_sourcer.draft_creator import (
    _candidate_to_params,
    enqueue_drafts_for_approval,
    mint_drafts_immediately,
)


# ── Helpers ──────────────────────────────────────────────────


def _sample_candidate():
    return {
        "name": "Test Bamboo Spice Rack",
        "category": "Kitchen",
        "description": "Counter-top bamboo organizer.",
        "price_min": 18.0,
        "price_max": 38.0,
        "suggested_price": 27.99,
        "tags": ["home", "bamboo", "organizer"],
        "vendor_hint": "Houseware wholesale",
    }


# ── _candidate_to_params ─────────────────────────────────────


class TestCandidateToParams:
    def test_translates_required_fields(self):
        cand = _sample_candidate()
        params = _candidate_to_params(cand, niche="home")
        assert params["title"] == "Test Bamboo Spice Rack"
        assert params["status"] == "DRAFT"
        assert params["product_type"] == "Kitchen"
        assert "<p>" in params["description"]
        assert params["tags"] == [
            "home", "bamboo", "organizer",
        ]

    def test_carries_metadata_block(self):
        cand = _sample_candidate()
        params = _candidate_to_params(cand, niche="home")
        meta = params.get("_metadata") or {}
        assert meta.get("source") == "product_sourcer"
        assert meta.get("niche") == "home"
        assert meta.get("suggested_price") == 27.99

    def test_empty_description_yields_empty_body(self):
        cand = _sample_candidate()
        cand["description"] = ""
        params = _candidate_to_params(cand, niche="home")
        assert params["description"] == ""

    def test_non_list_tags_become_empty(self):
        cand = _sample_candidate()
        cand["tags"] = "not-a-list"
        params = _candidate_to_params(cand, niche="home")
        assert params["tags"] == []


# ── enqueue_drafts_for_approval ─────────────────────────────


class TestEnqueueDrafts:
    def test_empty_list_returns_empty(self):
        out = enqueue_drafts_for_approval([], niche="home")
        assert out == []

    def test_non_list_returns_empty(self):
        # type: ignore[arg-type]
        out = enqueue_drafts_for_approval(
            "not a list", niche="home",  # type: ignore[arg-type]
        )
        assert out == []

    def test_each_candidate_enqueues_one_action(self):
        cand1 = _sample_candidate()
        cand2 = dict(cand1, name="Second Item")
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = [
            MagicMock(id="appr_1"),
            MagicMock(id="appr_2"),
        ]
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            out = enqueue_drafts_for_approval(
                [cand1, cand2], niche="home",
            )
        assert len(out) == 2
        assert out[0]["pending_action_id"] == "appr_1"
        assert out[1]["pending_action_id"] == "appr_2"

    def test_missing_name_skipped(self):
        cand = _sample_candidate()
        cand["name"] = ""
        fake_queue = MagicMock()
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            out = enqueue_drafts_for_approval(
                [cand], niche="home",
            )
        assert out == []
        fake_queue.enqueue.assert_not_called()

    def test_queue_import_failure_returns_empty(self):
        cand = _sample_candidate()
        with patch(
            "core.approval.get_approval_queue",
            side_effect=ImportError("no queue"),
        ):
            out = enqueue_drafts_for_approval(
                [cand], niche="home",
            )
        assert out == []

    def test_per_candidate_enqueue_failure_drops_one(self):
        cand1 = _sample_candidate()
        cand2 = dict(cand1, name="Second Item")
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = [
            RuntimeError("queue full"),
            MagicMock(id="appr_2"),
        ]
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            out = enqueue_drafts_for_approval(
                [cand1, cand2], niche="home",
            )
        assert len(out) == 1
        assert out[0]["pending_action_id"] == "appr_2"


# ── mint_drafts_immediately ─────────────────────────────────


class TestMintImmediate:
    def test_empty_list_returns_empty(self):
        out = mint_drafts_immediately([], niche="home")
        assert out == []

    def test_router_missing_yields_router_missing(self):
        cand = _sample_candidate()
        with patch(
            "core.adapters.router.get_router",
            side_effect=ImportError("no router"),
        ):
            out = mint_drafts_immediately([cand], niche="home")
        assert len(out) == 1
        assert out[0]["status"] == "router_missing"

    def test_successful_mint_returns_product_id(self):
        cand = _sample_candidate()
        fake_router = MagicMock()
        ok_result = MagicMock(
            ok=True, data={"product_id": "gid://shopify/Product/42"},
        )
        fake_router.execute.return_value = ok_result
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            out = mint_drafts_immediately([cand], niche="home")
        assert len(out) == 1
        assert out[0]["status"] == "minted"
        assert "Product/42" in out[0]["product_id"]

    def test_adapter_failure_recorded_as_error(self):
        cand = _sample_candidate()
        fake_router = MagicMock()
        fail_result = MagicMock(
            ok=False, data=None, error="title taken",
        )
        fake_router.execute.return_value = fail_result
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            out = mint_drafts_immediately([cand], niche="home")
        assert len(out) == 1
        assert out[0]["status"] == "error"
        assert "title taken" in (out[0]["error"] or "")

    def test_router_raises_recorded_as_error(self):
        cand = _sample_candidate()
        fake_router = MagicMock()
        fake_router.execute.side_effect = RuntimeError("boom")
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            out = mint_drafts_immediately([cand], niche="home")
        assert len(out) == 1
        assert out[0]["status"] == "error"
        assert "RuntimeError" in (out[0]["error"] or "")


# ── Engine end-to-end ───────────────────────────────────────


class TestEngineApply:
    def test_default_no_apply_returns_only_candidates(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "beauty", "count": 2},
        })
        assert result["data"]["pending_actions"] == []
        assert result["data"]["minted_drafts"] == []

    def test_apply_with_default_uses_approval_queue(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = lambda **kw: MagicMock(
            id="appr_" + kw["params"]["title"][:8],
        )
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            result = ProductSourcerEngine().run({
                "data": {
                    "niche": "beauty", "count": 3,
                    "apply_candidates": True,
                },
            })
        assert len(result["data"]["pending_actions"]) == 3
        assert result["data"]["minted_drafts"] == []
        assert "enqueued" in result["data"]["next_action"]

    def test_apply_with_mint_direct_uses_router(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"product_id": "gid://shopify/Product/1"},
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = ProductSourcerEngine().run({
                "data": {
                    "niche": "tech", "count": 2,
                    "apply_candidates": True,
                    "require_approval": False,
                },
            })
        assert result["data"]["pending_actions"] == []
        assert len(result["data"]["minted_drafts"]) == 2
        assert "draft(s) created" in result["data"]["next_action"]
