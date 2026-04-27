"""Tests for ``core.approval.executor.execute_action``.

Closes the loop the queue (PR #57) and the nine engine wireups
opened. Coverage:

  1. Registry — all nine action_types register on first call.
  2. ``execute_action`` lifecycle:
     * unknown id → None.
     * non-APPROVED state → None (idempotent: no mutation).
     * dispatcher success → status=EXECUTED, result populated.
     * dispatcher failure → status=FAILED, result.error populated.
     * dispatcher raise → caught, status=FAILED with
       ``dispatcher_raised:`` prefix.
  3. Per-dispatcher params validation — every dispatcher
     surfaces a structured ``error`` on missing required fields.
  4. Router-call dispatchers (7 of 9) forward the right friendly
     params shape; the two mint dispatchers reuse the shared
     ``mint_recovery_code`` helper.
  5. ``apply_description`` refuses replay when the parked body
     was truncated (a known limitation flagged at enqueue time).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.approval.executor import (
    _DISPATCHERS,
    _ensure_dispatchers_loaded,
    execute_action,
    list_registered_action_types,
)
from core.approval.queue import ApprovalQueue, ApprovalStatus


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def loaded_dispatchers():
    """Force the dispatcher registry to load before the test runs."""
    _ensure_dispatchers_loaded()
    yield


# ─── registry ────────────────────────────────────────────────────


class TestRegistry:

    def test_all_nine_action_types_register(self, loaded_dispatchers):
        types = set(list_registered_action_types())
        assert types == {
            "mint_strategy_code",
            "mint_loyalty_code",
            "apply_price_change",
            "apply_tags",
            "pay_commission",
            "archive_declining_product",
            "apply_description",
            "apply_seo_meta",
            "catalog_apply_tags",
        }

    def test_dispatchers_are_callables(self, loaded_dispatchers):
        for action_type, fn in _DISPATCHERS.items():
            assert callable(fn), f"{action_type} dispatcher is not callable"


# ─── execute_action lifecycle ───────────────────────────────────


class TestExecuteActionLifecycle:

    def test_unknown_id_returns_none(self, isolated_queue, loaded_dispatchers):
        assert execute_action("appr_does_not_exist_123") is None

    def test_pending_action_is_noop(self, isolated_queue, loaded_dispatchers):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        # Not approved yet — execute must refuse.
        assert execute_action(action.id) is None
        # State unchanged.
        current = isolated_queue.get(action.id)
        assert current is not None
        assert current.status == ApprovalStatus.PENDING

    def test_already_executed_action_is_noop(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)
        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"id": "p1"}),
        ):
            execute_action(action.id)
        # Second execute returns None (idempotent).
        assert execute_action(action.id) is None
        current = isolated_queue.get(action.id)
        assert current is not None
        assert current.status == ApprovalStatus.EXECUTED

    def test_dispatcher_success_flips_to_executed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id, decided_by="op")

        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"shopify_id": "gid://1"}),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.EXECUTED
        assert result.result == {"shopify_id": "gid://1"}

    def test_dispatcher_failure_flips_to_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)

        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(False, {"error": "scope_missing"}),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert result.result == {"error": "scope_missing"}

    def test_dispatcher_raise_caught_and_marked_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=RuntimeError("network"),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert "dispatcher_raised" in result.result["error"]
        assert "network" in result.result["error"]

    def test_unknown_action_type_marks_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="future_engine",
            action_type="do_something_new",
            capability="SHOPIFY_UNKNOWN",
            params={},
        )
        isolated_queue.approve(action.id)

        result = execute_action(action.id)
        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert "no executor registered" in result.result["error"]


# ─── per-dispatcher param validation ────────────────────────────


class TestPerDispatcherValidation:

    @pytest.mark.parametrize("action_type, bad_params", [
        ("apply_tags", {}),  # missing product_id + tags
        ("apply_tags", {"product_id": "p1", "merged_tags": []}),
        ("catalog_apply_tags", {"product_id": "", "tags": ["x"]}),
        ("catalog_apply_tags", {"product_id": "p1", "tags": []}),
        ("apply_seo_meta", {}),
        ("apply_seo_meta", {"product_id": "p1"}),  # no title or desc
        ("archive_declining_product", {}),
        ("apply_price_change", {"product_id": "p1", "new_price": 10}),  # no variant_ids
        ("apply_price_change", {"product_id": "p1", "new_price": "abc",
                                 "variant_ids": ["v1"]}),
        ("pay_commission", {}),
        ("mint_loyalty_code", {}),
        ("mint_loyalty_code", {"customer_id": "c1"}),  # no percentage
        ("mint_strategy_code", {}),
        ("apply_description", {}),
    ])
    def test_missing_params_surface_structured_error(
        self, action_type, bad_params, loaded_dispatchers,
    ):
        dispatcher = _DISPATCHERS[action_type]
        success, result = dispatcher(bad_params)
        assert success is False
        assert isinstance(result, dict)
        assert "error" in result and result["error"]


# ─── per-dispatcher happy-path forwarding ──────────────────────


class TestRouterForwardingDispatchers:

    def test_apply_tags_forwards_merged_list(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            success, _ = _DISPATCHERS["apply_tags"]({
                "product_id": "p1",
                "merged_tags": ["existing", "auto-tag"],
            })

        assert success is True
        assert captured["cap"] == "SHOPIFY_UPDATE_PRODUCT"
        assert captured["params"] == {
            "id": "p1", "tags": ["existing", "auto-tag"],
        }

    def test_catalog_uses_add_tags_capability(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["catalog_apply_tags"]({
                "product_id": "p1", "tags": ["a", "b"],
            })

        assert captured["cap"] == "SHOPIFY_ADD_TAGS"
        assert captured["params"] == {"id": "p1", "tags": ["a", "b"]}

    def test_seo_meta_emits_only_changed_fields(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_seo_meta"]({
                "product_id": "p1",
                "proposed_title": "New Title",
                "proposed_description": None,
            })

        assert captured["params"] == {
            "id": "p1", "seo_title": "New Title",
        }
        assert "seo_description" not in captured["params"]

    def test_archive_uses_status_archived(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["archive_declining_product"]({
                "product_id": "p1", "status": "ARCHIVED",
            })

        assert captured["params"] == {"id": "p1", "status": "ARCHIVED"}

    def test_price_change_rebuilds_variants_payload(
        self, loaded_dispatchers,
    ):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_price_change"]({
                "product_id": "p1",
                "new_price": 19.5,
                "variant_ids": ["v1", "v2"],
            })

        assert captured["params"]["product_id"] == "p1"
        assert captured["params"]["variants"] == [
            {"id": "v1", "price": "19.50"},
            {"id": "v2", "price": "19.50"},
        ]

    def test_pay_commission_forwards_params_directly(
        self, loaded_dispatchers,
    ):
        # Affiliate's enqueue already builds the gift-card friendly
        # form, so the dispatcher is a direct forward.
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        gift_params = {
            "initial_value": 50.0,
            "currency": "USD",
            "note": "Affiliate commission test",
            "recipient_email": "a@example.com",
        }
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["pay_commission"](gift_params)

        assert captured["cap"] == "SHOPIFY_CREATE_GIFT_CARD"
        # Direct copy — every field passed through.
        assert captured["params"] == gift_params


# ─── mint dispatchers ──────────────────────────────────────────


class TestMintDispatchers:

    def test_mint_loyalty_calls_shared_helper(self, loaded_dispatchers):
        captured: dict = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {"code": "LOYALTY-X", "discount_id": "1"}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub_mint,
        ):
            success, result = _DISPATCHERS["mint_loyalty_code"]({
                "customer_id": "gid://shopify/Customer/123",
                "percentage": 10.0,
                "ttl_days": 14,
            })

        assert success is True
        assert result["code"] == "LOYALTY-X"
        assert captured["code_prefix"] == "LOYALTY"
        assert captured["value"] == 10.0
        assert captured["value_kind"] == "percentage"
        assert captured["ttl_days"] == 14
        # Token derived from customer_id.
        assert captured["token"]

    def test_mint_strategy_uses_storewide_flags(self, loaded_dispatchers):
        captured: dict = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {"code": "PROMO-Y"}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub_mint,
        ):
            success, result = _DISPATCHERS["mint_strategy_code"]({
                "audience": "all",
                "percentage": 15.0,
                "ttl_days": 7,
            })

        assert success is True
        assert captured["code_prefix"] == "PROMO"
        # Storewide flags differ from loyalty.
        assert captured["usage_limit"] is None
        assert captured["applies_once_per_customer"] is False

    def test_mint_returns_none_marks_failed(self, loaded_dispatchers):
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            return_value=None,
        ):
            success, result = _DISPATCHERS["mint_loyalty_code"]({
                "customer_id": "gid://shopify/Customer/1",
                "percentage": 10.0,
            })
        assert success is False
        assert result["error"] == "mint_returned_none"


# ─── apply_description body-truncation guard ───────────────────


class TestApplyDescriptionGuard:

    def test_truncated_body_refuses_replay(self, loaded_dispatchers):
        # body_length > len(body_preview) → enqueue truncated;
        # dispatcher refuses to replay rather than write a partial
        # description.
        success, result = _DISPATCHERS["apply_description"]({
            "product_id": "p1",
            "body_length": 5000,
            "body_preview": "x" * 200,
        })
        assert success is False
        assert "body_truncated_in_queue" in result["error"]

    def test_short_body_replays(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            success, _ = _DISPATCHERS["apply_description"]({
                "product_id": "p1",
                "body_length": 50,
                "body_preview": "x" * 50,
            })

        assert success is True
        assert captured["params"]["id"] == "p1"
        assert captured["params"]["description_html"] == "x" * 50
