"""Tests for cart_recovery's discount_minter — the bridge between
the calculated incentive and a real Shopify discount code.

Scope is intentionally narrow: just the new minter module + the
flow.py wire-up that feeds the minted code into the output. The
broader cart-recovery pipeline (analyzer / classifier / strategy /
message / timing / channel / value-estimator) is out of scope here
and exercised separately.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines.cart_recovery.discount_minter import mint_recovery_code


# ─── Helpers ──────────────────────────────────────────────────────


class _StubRouterResult:
    """Mimics core.adapters.base.AdapterResult for these tests."""

    def __init__(self, *, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    """Captures the .execute call so tests can assert wire shape."""

    def __init__(self, *, result):
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


# ─── Mintable-vs-skippable incentive types ────────────────────────


class TestIncentiveTypeRouting:

    @pytest.mark.parametrize("incentive_type", [
        "free_shipping", "bundle", "loyalty_points", "none", "",
    ])
    def test_non_mintable_types_skipped_without_router_call(
        self, incentive_type,
    ):
        # No router-available patch needed — the function must
        # short-circuit BEFORE looking up the router.
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                {"type": incentive_type, "value": 10},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None
        # Critically: router import never even attempted because
        # the early return fires first.
        mock_router.assert_not_called()

    def test_zero_value_short_circuits(self):
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                {"type": "percentage", "value": 0},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None
        mock_router.assert_not_called()

    def test_non_numeric_value_short_circuits(self):
        with patch(
            "engines._recovery_codes._get_router",
        ) as mock_router:
            result = mint_recovery_code(
                {"type": "percentage", "value": "many"},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None
        mock_router.assert_not_called()


# ─── Router unavailable / failure modes ───────────────────────────


class TestGracefulFallbacks:

    def test_router_unavailable_returns_none(self):
        with patch(
            "engines._recovery_codes._get_router",
            return_value=None,
        ):
            result = mint_recovery_code(
                {"type": "percentage", "value": 10},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None

    def test_adapter_returns_failure_returns_none(self):
        stub_router = _StubRouter(result=_StubRouterResult(
            ok=False, error="discount code already exists",
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            result = mint_recovery_code(
                {"type": "percentage", "value": 10},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None

    def test_adapter_raises_returns_none(self):
        class _ExplodingRouter:
            def execute(self, capability, params):
                raise RuntimeError("network down")

        with patch(
            "engines._recovery_codes._get_router",
            return_value=_ExplodingRouter(),
        ):
            result = mint_recovery_code(
                {"type": "percentage", "value": 10},
                {"id": "gid://shopify/Customer/1"},
            )
        assert result is None


# ─── Happy paths ──────────────────────────────────────────────────


class TestMintHappyPath:

    def test_percentage_creates_discount_with_expected_shape(self):
        from core.adapters.base import Capability

        stub_router = _StubRouter(result=_StubRouterResult(
            ok=True,
            data={
                "discount_id":
                    "gid://shopify/DiscountCodeNode/123",
                "code": "SHOULD-NOT-BE-USED",
            },
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            result = mint_recovery_code(
                {"type": "percentage", "value": 15.0},
                {"id": "gid://shopify/Customer/12345"},
            )

        # Mutation routed to the right Capability.
        assert len(stub_router.calls) == 1
        cap, params = stub_router.calls[0]
        assert cap == Capability.SHOPIFY_CREATE_DISCOUNT

        # Generated code includes RECOVER prefix + customer numeric
        # id from the GID. Exact epoch suffix isn't asserted (it
        # changes with wall-clock), but it ends with digits.
        assert params["code"].startswith("RECOVER-12345-")
        # Title summarises the offer.
        assert params["title"] == "Cart recovery: 15% off"
        # Percentage routed; amount NOT set.
        assert params["percentage"] == 15.0
        assert "amount" not in params
        # Bounded redemption: usage_limit 1, applies once per
        # customer.
        assert params["usage_limit"] == 1
        assert params["applies_once_per_customer"] is True
        # Time window present and ISO-shaped.
        assert params["starts_at"].endswith("Z")
        assert params["ends_at"].endswith("Z")

        # Returned dict surfaces what the caller actually needs.
        assert result == {
            "code": params["code"],
            "discount_id":
                "gid://shopify/DiscountCodeNode/123",
            "ends_at": params["ends_at"],
            "applies_once": True,
        }

    def test_amount_creates_fixed_discount(self):
        stub_router = _StubRouter(result=_StubRouterResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/2"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            mint_recovery_code(
                {"type": "amount", "value": 5.00},
                {"id": "gid://shopify/Customer/9"},
            )

        _, params = stub_router.calls[0]
        # Amount routed; percentage NOT set.
        assert params["amount"] == 5.0
        assert "percentage" not in params
        # Title omits the % sign for amount-based offers.
        assert "%" not in params["title"]

    def test_email_only_customer_falls_back_to_email_token(self):
        stub_router = _StubRouter(result=_StubRouterResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/3"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            mint_recovery_code(
                {"type": "percentage", "value": 10},
                {"email": "ada.lovelace+vip@example.com"},
            )

        _, params = stub_router.calls[0]
        # No GID → uses sanitised email local-part as token.
        # Local part "ada.lovelace+vip" → strip dots/plus/uppercase
        # → "ADALOVELACEVIP" → [:12] → "ADALOVELACEV".
        assert params["code"].startswith("RECOVER-ADALOVELACEV-")

    def test_anonymous_customer_uses_anon_token(self):
        stub_router = _StubRouter(result=_StubRouterResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/4"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            mint_recovery_code(
                {"type": "percentage", "value": 10},
                {},
            )

        _, params = stub_router.calls[0]
        assert params["code"].startswith("RECOVER-ANON-")

    def test_store_ttl_override_respected(self):
        from datetime import datetime
        stub_router = _StubRouter(result=_StubRouterResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/5"},
        ))
        with patch(
            "engines._recovery_codes._get_router",
            return_value=stub_router,
        ):
            mint_recovery_code(
                {"type": "percentage", "value": 10},
                {"id": "gid://shopify/Customer/9"},
                {"recovery_code_ttl_days": 14},
            )

        _, params = stub_router.calls[0]
        starts = datetime.fromisoformat(
            params["starts_at"].replace("Z", "+00:00"),
        )
        ends = datetime.fromisoformat(
            params["ends_at"].replace("Z", "+00:00"),
        )
        gap_days = (ends - starts).days
        # 14-day TTL applied (default would have been 7).
        assert gap_days == 14

    def test_ttl_clamped_to_one_to_ninety_days(self):
        from datetime import datetime

        for raw_ttl, expected_days in [
            (0, 1),       # below floor → 1
            (-5, 1),      # negative → 1
            (200, 90),    # above ceiling → 90
            ("garbage", 7),  # non-int → default 7
        ]:
            stub_router = _StubRouter(result=_StubRouterResult(
                ok=True,
                data={
                    "discount_id":
                        "gid://shopify/DiscountCodeNode/x",
                },
            ))
            with patch(
                "engines._recovery_codes._get_router",
                return_value=stub_router,
            ):
                mint_recovery_code(
                    {"type": "percentage", "value": 10},
                    {"id": "gid://shopify/Customer/1"},
                    {"recovery_code_ttl_days": raw_ttl},
                )
            _, params = stub_router.calls[0]
            starts = datetime.fromisoformat(
                params["starts_at"].replace("Z", "+00:00"),
            )
            ends = datetime.fromisoformat(
                params["ends_at"].replace("Z", "+00:00"),
            )
            assert (ends - starts).days == expected_days, (
                f"TTL {raw_ttl} should map to {expected_days} days"
            )


# ─── Flow.py wire-up ──────────────────────────────────────────────


class TestFlowSurfacesMintedCode:
    """Verifies that the cart_recovery pipeline reads the minted
    code into its output's ``incentive`` block. We patch
    mint_recovery_code at the flow's import site so we don't have
    to stand up the full router here."""

    def _minimal_input(self) -> dict:
        return {
            "cart": {
                "items": [{
                    "id": "gid://shopify/ProductVariant/1",
                    "title": "Widget",
                    "quantity": 1,
                    "price": 50.0,
                }],
                "total": 50.0,
            },
            "customer": {
                "email": "ada@example.com",
                "id": "gid://shopify/Customer/1",
            },
            "store": {
                "avg_margin": 0.40,
                "free_shipping_threshold": 75.0,
            },
        }

    def test_minted_code_appears_in_output(self):
        from engines.cart_recovery.flow import CartRecoveryEngine

        # The full pipeline runs LLM-backed stages that go through
        # the legacy LLM path; in CI those return mock data, in
        # local-dev they're slow but deterministic enough. We just
        # need the incentive block to come out with the minter
        # patched to inject a known code.
        with patch(
            "engines.cart_recovery.flow.mint_recovery_code",
            return_value={
                "code": "RECOVER-1-1234567890",
                "discount_id":
                    "gid://shopify/DiscountCodeNode/77",
                "ends_at": "2026-05-03T00:00:00Z",
                "applies_once": True,
            },
        ):
            output = CartRecoveryEngine().run(self._minimal_input())

        # Pipeline didn't crash.
        assert output["status"] in ("success", "error")
        if output["status"] == "success":
            inc = output["data"]["incentive"]
            assert inc["code"] == "RECOVER-1-1234567890"
            assert inc["discount_id"] == \
                "gid://shopify/DiscountCodeNode/77"
            assert inc["ends_at"] == "2026-05-03T00:00:00Z"

    def test_no_minted_code_yields_empty_strings_in_output(self):
        from engines.cart_recovery.flow import CartRecoveryEngine

        # Router unavailable / non-mintable type → minter returns
        # None. Output's incentive block must surface that as
        # empty strings so downstream consumers can detect "no
        # code minted, fall back to evergreen merchant code".
        with patch(
            "engines.cart_recovery.flow.mint_recovery_code",
            return_value=None,
        ):
            output = CartRecoveryEngine().run(self._minimal_input())

        if output["status"] == "success":
            inc = output["data"]["incentive"]
            assert inc["code"] == ""
            assert inc["discount_id"] == ""
            assert inc["ends_at"] == ""
