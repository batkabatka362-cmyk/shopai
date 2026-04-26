"""Tests for browse_recovery's discount_minter — mints a Shopify
discount code per qualifying offer (high/medium-intent abandoner).

Differs from cart_recovery's minter in shape (N users → N codes,
mutates offers in place). Pattern + graceful-fallback contract is
the same.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.browse_recovery.discount_minter import mint_offer_codes


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


def _three_offers():
    """Build three offers + matching intent scores: high, medium,
    low. Returns (offers, intent_scores)."""
    offers = [
        {
            "user_id": "u_high",
            "offer_type": "gentle_reminder",
            "discount_pct": 5.0,
            "urgency": "low",
            "message": "still interested?",
        },
        {
            "user_id": "u_med",
            "offer_type": "incentive",
            "discount_pct": 10.0,
            "urgency": "medium",
            "message": "10% off",
        },
        {
            "user_id": "u_low",
            "offer_type": "aggressive_discount",
            "discount_pct": 20.0,
            "urgency": "high",
            "message": "20% off!",
        },
    ]
    intent_scores = [
        {"user_id": "u_high", "purchase_likelihood": "high",
         "intent_score": 80.0},
        {"user_id": "u_med", "purchase_likelihood": "medium",
         "intent_score": 50.0},
        {"user_id": "u_low", "purchase_likelihood": "low",
         "intent_score": 15.0},
    ]
    return offers, intent_scores


# ─── Empty / no-op cases ──────────────────────────────────────────


class TestEmptyAndShortCircuits:

    def test_empty_offers_returns_unchanged(self):
        # No router lookup should happen at all.
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
        ) as mock_router:
            result = mint_offer_codes(
                offers=[], intent_scores=[],
            )
        assert result == []
        mock_router.assert_not_called()

    def test_router_unavailable_stamps_skipped_on_all(self):
        offers, intent_scores = _three_offers()
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=None,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )
        # Every offer gets the four "skipped" fields stamped on so
        # the downstream contract is consistent.
        for offer in offers:
            assert offer["code"] == ""
            assert offer["discount_id"] == ""
            assert offer["ends_at"] == ""
            assert offer["minted"] is False


# ─── Likelihood filter ────────────────────────────────────────────


class TestLikelihoodFilter:

    def test_default_filter_mints_only_high_and_medium(self):
        offers, intent_scores = _three_offers()
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/1"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )

        # 2 of 3 offers got minted (high + medium); low was skipped.
        assert len(stub.calls) == 2
        called_users = {
            params["code"].split("-")[1] for _, params in stub.calls
        }
        assert called_users == {"UHIGH", "UMED"}

        # Per-offer state mirrors that.
        by_user = {o["user_id"]: o for o in offers}
        assert by_user["u_high"]["minted"] is True
        assert by_user["u_med"]["minted"] is True
        assert by_user["u_low"]["minted"] is False
        # Skipped offer still has empty code fields.
        assert by_user["u_low"]["code"] == ""

    def test_custom_filter_includes_low_intent(self):
        offers, intent_scores = _three_offers()
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers,
                intent_scores=intent_scores,
                mintable_likelihoods={"high", "medium", "low"},
            )
        # All 3 minted now.
        assert len(stub.calls) == 3
        for offer in offers:
            assert offer["minted"] is True

    def test_custom_filter_only_high_skips_medium(self):
        offers, intent_scores = _three_offers()
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers,
                intent_scores=intent_scores,
                mintable_likelihoods={"high"},
            )
        assert len(stub.calls) == 1
        by_user = {o["user_id"]: o for o in offers}
        assert by_user["u_high"]["minted"] is True
        assert by_user["u_med"]["minted"] is False
        assert by_user["u_low"]["minted"] is False

    def test_user_with_no_intent_score_treated_as_low(self):
        # Offer carries a user_id that ISN'T in intent_scores → the
        # likelihood lookup returns "low" by default → skipped under
        # the default filter.
        offers = [{"user_id": "ghost", "discount_pct": 10.0}]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(offers=offers, intent_scores=[])
        assert stub.calls == []
        assert offers[0]["minted"] is False


# ─── Per-offer skip cases ─────────────────────────────────────────


class TestPerOfferSkips:

    def test_zero_discount_pct_is_skipped(self):
        offers = [{
            "user_id": "u1",
            "discount_pct": 0,  # nothing to mint
        }]
        intent_scores = [{
            "user_id": "u1", "purchase_likelihood": "high",
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )
        assert stub.calls == []
        assert offers[0]["minted"] is False

    def test_non_numeric_discount_pct_is_skipped(self):
        offers = [{"user_id": "u1", "discount_pct": "garbage"}]
        intent_scores = [{
            "user_id": "u1", "purchase_likelihood": "high",
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )
        assert stub.calls == []
        assert offers[0]["minted"] is False

    def test_adapter_failure_skips_only_that_offer(self):
        offers, intent_scores = _three_offers()
        # Router fails (returns ok=False) regardless of input.
        stub = _StubRouter(result=_StubResult(
            ok=False, error="Code already exists",
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )
        # Both high + medium attempted, both failed → both
        # stamped skipped.
        by_user = {o["user_id"]: o for o in offers}
        assert by_user["u_high"]["minted"] is False
        assert by_user["u_med"]["minted"] is False

    def test_adapter_raises_skips_only_that_offer(self):
        offers, intent_scores = _three_offers()

        class _PartialFailRouter:
            """Raises on first call, succeeds on second."""
            def __init__(self):
                self.calls: list[tuple] = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                if len(self.calls) == 1:
                    raise RuntimeError("network blip")
                return _StubResult(
                    ok=True, data={"discount_id": "gid://x"},
                )

        stub = _PartialFailRouter()
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )

        # First call (u_high) raised → skipped.
        # Second call (u_med) succeeded → minted.
        by_user = {o["user_id"]: o for o in offers}
        assert by_user["u_high"]["minted"] is False
        assert by_user["u_high"]["code"] == ""
        assert by_user["u_med"]["minted"] is True
        assert by_user["u_med"]["code"].startswith("BROWSE-UMED-")
        # Low never attempted (filtered out by default).
        assert by_user["u_low"]["minted"] is False


# ─── Wire shape on success ────────────────────────────────────────


class TestWireShape:

    def test_mint_call_uses_create_discount_capability(self):
        from core.adapters.base import Capability

        offers, intent_scores = _three_offers()
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/1"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )

        for cap, _params in stub.calls:
            assert cap == Capability.SHOPIFY_CREATE_DISCOUNT

    def test_mint_call_carries_expected_input_shape(self):
        offers, intent_scores = _three_offers()
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"discount_id": "gid://shopify/DiscountCodeNode/1"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )

        # Inspect the high-intent call.
        high_params = next(
            params for _, params in stub.calls
            if "UHIGH" in params["code"]
        )
        # BROWSE prefix + uppercased+sanitised user_id token + epoch.
        assert high_params["code"].startswith("BROWSE-UHIGH-")
        # Title summarises the offer + likelihood.
        assert "(high intent)" in high_params["title"]
        assert high_params["percentage"] == 5.0
        # Bounded redemption.
        assert high_params["usage_limit"] == 1
        assert high_params["applies_once_per_customer"] is True
        # ISO time window.
        assert high_params["starts_at"].endswith("Z")
        assert high_params["ends_at"].endswith("Z")

    def test_response_data_threaded_into_offer(self):
        offers, intent_scores = _three_offers()
        # Different discount_id per call to verify each offer gets
        # its own minted id.
        responses = iter([
            _StubResult(
                ok=True,
                data={
                    "discount_id":
                        "gid://shopify/DiscountCodeNode/aa",
                },
            ),
            _StubResult(
                ok=True,
                data={
                    "discount_id":
                        "gid://shopify/DiscountCodeNode/bb",
                },
            ),
        ])

        class _SeqRouter:
            calls: list[tuple] = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return next(responses)

        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=_SeqRouter(),
        ):
            mint_offer_codes(
                offers=offers, intent_scores=intent_scores,
            )

        by_user = {o["user_id"]: o for o in offers}
        # Both minted offers got distinct discount_ids back.
        assert by_user["u_high"]["discount_id"] == \
            "gid://shopify/DiscountCodeNode/aa"
        assert by_user["u_med"]["discount_id"] == \
            "gid://shopify/DiscountCodeNode/bb"


# ─── TTL handling ─────────────────────────────────────────────────


class TestTtlOverride:

    def test_store_ttl_override_respected(self):
        from datetime import datetime
        offers = [{"user_id": "u1", "discount_pct": 10.0}]
        intent_scores = [{
            "user_id": "u1", "purchase_likelihood": "high",
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"discount_id": "gid://x"},
        ))
        with patch(
            "engines.browse_recovery.discount_minter._get_router",
            return_value=stub,
        ):
            mint_offer_codes(
                offers=offers,
                intent_scores=intent_scores,
                store={"recovery_code_ttl_days": 30},
            )
        _, params = stub.calls[0]
        starts = datetime.fromisoformat(
            params["starts_at"].replace("Z", "+00:00"),
        )
        ends = datetime.fromisoformat(
            params["ends_at"].replace("Z", "+00:00"),
        )
        assert (ends - starts).days == 30

    def test_ttl_clamped(self):
        from datetime import datetime
        for raw, expected in [
            (-1, 1), (0, 1), (200, 90), ("garbage", 7),
        ]:
            offers = [{"user_id": "u1", "discount_pct": 10.0}]
            intent_scores = [{
                "user_id": "u1", "purchase_likelihood": "high",
            }]
            stub = _StubRouter(result=_StubResult(
                ok=True, data={"discount_id": "gid://x"},
            ))
            with patch(
                "engines.browse_recovery.discount_minter._get_router",
                return_value=stub,
            ):
                mint_offer_codes(
                    offers=offers,
                    intent_scores=intent_scores,
                    store={"recovery_code_ttl_days": raw},
                )
            _, params = stub.calls[0]
            starts = datetime.fromisoformat(
                params["starts_at"].replace("Z", "+00:00"),
            )
            ends = datetime.fromisoformat(
                params["ends_at"].replace("Z", "+00:00"),
            )
            assert (ends - starts).days == expected, (
                f"TTL {raw} should map to {expected} days"
            )


# ─── Flow integration ─────────────────────────────────────────────


class TestFlowIntegration:
    """Verifies that the browse_recovery pipeline calls the minter
    and surfaces the resulting code through to recovery_targets."""

    def _minimal_input(self):
        return {
            "data": {
                "sessions": [
                    {
                        "user_id": "u_eager",
                        "pages_viewed": [
                            "/p/widget", "/p/widget", "/cart",
                            "/checkout", "/p/widget",
                            "/related", "/blog", "/widget",
                        ],
                        "products_viewed": ["pid_1", "pid_2"],
                        "duration": 600,
                        "cart_items": ["pid_1"],
                    },
                ],
                "products": [
                    {"id": "pid_1", "title": "Widget", "price": 50},
                ],
                "store": {"recovery_code_ttl_days": 7},
            },
        }

    def test_pipeline_calls_minter_and_threads_code(self):
        from engines.browse_recovery.flow import BrowseRecoveryEngine

        def _stub_minter(offers, intent_scores, store=None,
                         **kwargs):
            for o in offers:
                o["code"] = f"BROWSE-{o['user_id'].upper()}-1234"
                o["discount_id"] = "gid://shopify/DiscountCodeNode/9"
                o["ends_at"] = "2026-05-04T00:00:00Z"
                o["minted"] = True
            return offers

        with patch(
            "engines.browse_recovery.flow.mint_offer_codes",
            side_effect=_stub_minter,
        ):
            output = BrowseRecoveryEngine().run(self._minimal_input())

        assert output["status"] == "success"
        targets = output["data"]["recovery_targets"]
        assert len(targets) == 1
        offer = targets[0]["recommended_offer"]
        # Minted code threaded all the way through into the
        # recovery_target's recommended_offer.
        assert offer["code"].startswith("BROWSE-")
        assert offer["minted"] is True
        assert offer["discount_id"] == \
            "gid://shopify/DiscountCodeNode/9"

    def test_pipeline_continues_when_minter_skips_everyone(self):
        from engines.browse_recovery.flow import BrowseRecoveryEngine

        def _all_skipped(offers, intent_scores, store=None,
                         **kwargs):
            for o in offers:
                o["code"] = ""
                o["discount_id"] = ""
                o["ends_at"] = ""
                o["minted"] = False
            return offers

        with patch(
            "engines.browse_recovery.flow.mint_offer_codes",
            side_effect=_all_skipped,
        ):
            output = BrowseRecoveryEngine().run(self._minimal_input())

        assert output["status"] == "success"
        offer = output["data"]["recovery_targets"][0][
            "recommended_offer"
        ]
        assert offer["code"] == ""
        assert offer["minted"] is False
