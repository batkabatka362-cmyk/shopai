"""Tests for the shared Shopify utility modules in ``engines/``.

The per-engine wrappers (bundle/churn/cohort/catalog hydrators +
cart/browse-recovery minters) already have their own coverage via
their existing test files. This file targets the shared cores at
``engines._shopify_hydrator`` and ``engines._recovery_codes``
directly — the refactor surface that future engines will build on.
"""
from __future__ import annotations

from unittest.mock import patch

from engines._recovery_codes import (
    _build_code_name,
    _clamp_ttl,
    mint_recovery_code,
)
from engines._shopify_hydrator import _clamp_limit, hydrate


# ─── Stubs ────────────────────────────────────────────────────────


class _StubResult:
    def __init__(self, *, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, *, result):
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


# ─── Hydrator core ────────────────────────────────────────────────


class TestSharedHydrator:

    def test_supplied_passes_through_no_router_call(self):
        supplied = [{"id": "x"}]
        with patch(
            "engines._shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate(
                supplied=supplied,
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        assert result is supplied
        mock_router.assert_not_called()

    def test_unknown_capability_returns_empty(self):
        # An attribute name that doesn't exist on Capability falls
        # back to None and the hydrate call returns []. This makes
        # the shared core forward-compatible — engines can refer
        # to capabilities that haven't been added yet.
        with patch(
            "engines._shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate(
                supplied=[],
                capability_name="SHOPIFY_LIST_NONEXISTENT",
                list_field="things",
            )
        # Capability lookup returned None, so the function should
        # short-circuit BEFORE calling the router (or at minimum,
        # returns []). Implementation may or may not call
        # _get_router first.
        assert result == []

    def test_empty_input_calls_correct_capability(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "products": [{"id": "p1"}, {"id": "p2"}],
            },
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate(
                supplied=[],
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        cap, _ = stub.calls[0]
        assert cap == Capability.SHOPIFY_LIST_PRODUCTS
        assert len(result) == 2

    def test_extra_params_merged(self):
        # ``extra_params`` lets per-engine wrappers pass things like
        # sort_key / reverse / saved_search_id without each adding
        # its own boilerplate.
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate(
                supplied=[],
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
                extra_params={
                    "sort_key": "TITLE",
                    "reverse": True,
                    "explicit_none_dropped": None,
                },
            )
        _, params = stub.calls[0]
        assert params["sort_key"] == "TITLE"
        assert params["reverse"] is True
        # None values dropped (lets the adapter use its default).
        assert "explicit_none_dropped" not in params

    def test_max_limit_override(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate(
                supplied=[],
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
                limit=500,        # asks for 500
                max_limit=100,    # but engine caps at 100
            )
        _, params = stub.calls[0]
        assert params["limit"] == 100

    def test_blank_query_dropped(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate(
                supplied=[],
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
                query="   ",
            )
        _, params = stub.calls[0]
        assert "query" not in params


class TestClampLimit:

    def test_default(self):
        assert _clamp_limit(None) == 250

    def test_clamps_below_floor(self):
        assert _clamp_limit(0) == 1
        assert _clamp_limit(-100) == 1

    def test_clamps_above_ceiling(self):
        assert _clamp_limit(1000) == 250

    def test_max_limit_override_changes_default(self):
        # When max_limit is below the default floor of 250, the
        # default falls back to max_limit (so callers can
        # configure tighter caps and the function honors them
        # when no explicit limit is passed).
        assert _clamp_limit(None, max_limit=50) == 50

    def test_non_numeric_returns_default(self):
        assert _clamp_limit("garbage") == 250


# ─── Recovery-code core ───────────────────────────────────────────


class TestSharedMinter:

    def test_unknown_value_kind_returns_none(self):
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                token="X", code_prefix="REC",
                value=10, value_kind="bogus",
            )
        assert result is None
        # Must short-circuit BEFORE looking up the router.
        mock_router.assert_not_called()

    def test_zero_value_returns_none_no_router_call(self):
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                token="X", code_prefix="REC",
                value=0, value_kind="percentage",
            )
        assert result is None
        mock_router.assert_not_called()

    def test_negative_value_returns_none(self):
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                token="X", code_prefix="REC",
                value=-5, value_kind="amount",
            )
        assert result is None
        mock_router.assert_not_called()

    def test_router_unavailable_returns_none(self):
        with patch(
            "engines._recovery_codes._get_router",
            return_value=None,
        ):
            result = mint_recovery_code(
                token="X", code_prefix="REC",
                value=10, value_kind="percentage",
            )
        assert result is None

    def test_percentage_routed_correctly(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/1"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub,
        ):
            result = mint_recovery_code(
                token="USER123",
                code_prefix="RECOVER",
                value=15.0,
                value_kind="percentage",
                ttl_days=14,
                title="My title",
            )
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_CREATE_DISCOUNT
        assert params["percentage"] == 15.0
        assert "amount" not in params
        assert params["title"] == "My title"
        assert params["code"].startswith("RECOVER-USER123-")
        assert params["usage_limit"] == 1
        assert params["applies_once_per_customer"] is True
        assert result["code"] == params["code"]
        assert result["discount_id"] == \
            "gid://shopify/DiscountCodeNode/1"
        assert result["applies_once"] is True

    def test_amount_routed_correctly(self):
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub,
        ):
            mint_recovery_code(
                token="X", code_prefix="REC",
                value=5.0, value_kind="amount",
            )
        _, params = stub.calls[0]
        assert params["amount"] == 5.0
        assert "percentage" not in params

    def test_default_title_for_percentage(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub,
        ):
            mint_recovery_code(
                token="X", code_prefix="RECOVER",
                value=15, value_kind="percentage",
            )
        _, params = stub.calls[0]
        assert "%" in params["title"]
        assert "RECOVER" in params["title"]

    def test_default_title_for_amount_no_percent_sign(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub,
        ):
            mint_recovery_code(
                token="X", code_prefix="RECOVER",
                value=5, value_kind="amount",
            )
        _, params = stub.calls[0]
        assert "%" not in params["title"]

    def test_value_kind_case_insensitive(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub,
        ):
            result = mint_recovery_code(
                token="X", code_prefix="REC",
                value=10, value_kind="PERCENTAGE",
            )
        assert result is not None
        _, params = stub.calls[0]
        assert "percentage" in params


class TestBuildCodeName:

    def test_format_is_prefix_token_epoch(self):
        name = _build_code_name("RECOVER", "ABC123")
        assert name.startswith("RECOVER-ABC123-")
        # Epoch suffix is digits.
        suffix = name.rsplit("-", 1)[-1]
        assert suffix.isdigit()

    def test_capped_at_32_chars(self):
        # Long token + long prefix should still produce ≤32 chars.
        name = _build_code_name(
            "VERYLONGPREFIX",
            "VERYLONGTOKENVALUE",
        )
        assert len(name) <= 32

    def test_blank_token_falls_back_to_anon(self):
        name = _build_code_name("REC", "")
        assert "ANON" in name

    def test_blank_prefix_falls_back_to_rec(self):
        name = _build_code_name("", "TOKEN")
        assert name.startswith("REC-")


class TestClampTtl:

    def test_default(self):
        assert _clamp_ttl(None) == 7

    def test_clamps_below_floor(self):
        assert _clamp_ttl(0) == 1
        assert _clamp_ttl(-5) == 1

    def test_clamps_above_ceiling(self):
        assert _clamp_ttl(200) == 90

    def test_non_numeric_returns_default(self):
        assert _clamp_ttl("garbage") == 7

    def test_in_range_pass_through(self):
        assert _clamp_ttl(14) == 14
        assert _clamp_ttl(1) == 1
        assert _clamp_ttl(90) == 90
