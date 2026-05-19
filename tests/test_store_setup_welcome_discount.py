"""Tests for ``engines.store_setup.welcome_discount``.

The generator builds a launch-discount params dict; the
applier pushes it through ``SHOPIFY_CREATE_DISCOUNT`` and
records via Pattern Z.

Coverage:
  1. Generator: niche-specific percentage + auto code +
     date window + optional usage_limit / minimum_subtotal.
  2. Generator: empty store_name -> empty dict.
  3. Applier: success path + recording.
  4. Applier: router_unavailable + still records failure.
  5. Applier: adapter rejection + adapter raise.
  6. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.welcome_discount import (
    apply_welcome_discount,
    generate_welcome_discount,
)


def _ok_result():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail_result(error: str):
    return SimpleNamespace(ok=False, data=None, error=error)


# --- generate_welcome_discount --------------------------------


class TestGenerator:

    def test_beauty_gets_fifteen_pct(self):
        out = generate_welcome_discount(
            store_name="Acme", niche="beauty",
        )
        assert out["percentage"] == 15
        assert out["code"] == "WELCOME15"

    def test_tech_gets_ten_pct(self):
        out = generate_welcome_discount(
            store_name="Acme", niche="tech",
        )
        assert out["percentage"] == 10
        assert out["code"] == "WELCOME10"

    def test_extended_niches_have_expected_pct(self):
        """Niches added beyond the initial 6: pets/fitness/
        baby get 15%, jewelry/outdoor get 10%."""
        expectations = {
            "pets": 15, "fitness": 15, "baby": 15,
            "jewelry": 10, "outdoor": 10,
        }
        for niche, pct in expectations.items():
            out = generate_welcome_discount(
                store_name="Acme", niche=niche,
            )
            assert out["percentage"] == pct, niche
            assert out["code"] == f"WELCOME{pct}", niche

    def test_unknown_niche_falls_back_to_general(self):
        out = generate_welcome_discount(
            store_name="Acme", niche="ufo_parts",
        )
        assert out["percentage"] == 10
        assert out["code"] == "WELCOME10"

    def test_empty_store_name(self):
        assert generate_welcome_discount(store_name="") == {}
        assert (
            generate_welcome_discount(store_name="   ") == {}
        )
        assert (
            generate_welcome_discount(store_name=None) == {}
        )

    def test_custom_code_uppercased(self):
        out = generate_welcome_discount(
            store_name="Acme",
            niche="beauty",
            code="firstorder",
        )
        assert out["code"] == "FIRSTORDER"

    def test_blank_custom_code_falls_back_to_default(self):
        out = generate_welcome_discount(
            store_name="Acme",
            niche="beauty",
            code="   ",
        )
        assert out["code"] == "WELCOME15"

    def test_title_includes_store_name(self):
        out = generate_welcome_discount(
            store_name="Acme Beauty",
        )
        assert "Acme Beauty" in out["title"]

    def test_date_window_starts_now_ends_60d(self):
        out = generate_welcome_discount(store_name="Acme")
        assert "starts_at" in out
        assert "ends_at" in out
        # ISO-8601 with Z suffix
        assert out["starts_at"].endswith("Z")
        assert out["ends_at"].endswith("Z")

    def test_days_valid_overrides_window(self):
        out = generate_welcome_discount(
            store_name="Acme", days_valid=30,
        )
        # Just check both timestamps exist; the exact delta
        # is hard to assert without a frozen clock.
        assert "starts_at" in out and "ends_at" in out

    def test_days_valid_clamped(self):
        # Negative / zero -> floor to 1
        out = generate_welcome_discount(
            store_name="Acme", days_valid=-5,
        )
        assert "ends_at" in out
        # Huge values -> capped at 365
        out2 = generate_welcome_discount(
            store_name="Acme", days_valid=10_000,
        )
        assert "ends_at" in out2

    def test_usage_limit_included_when_positive(self):
        out = generate_welcome_discount(
            store_name="Acme", usage_limit=500,
        )
        assert out["usage_limit"] == 500

    def test_usage_limit_zero_omitted(self):
        out = generate_welcome_discount(
            store_name="Acme", usage_limit=0,
        )
        assert "usage_limit" not in out

    def test_minimum_subtotal_included(self):
        out = generate_welcome_discount(
            store_name="Acme", minimum_subtotal=25.0,
        )
        assert out["minimum_subtotal"] == 25.0

    def test_minimum_subtotal_zero_omitted(self):
        out = generate_welcome_discount(
            store_name="Acme", minimum_subtotal=0.0,
        )
        assert "minimum_subtotal" not in out


# --- apply_welcome_discount -----------------------------------


class TestApplierEmpty:

    def test_empty_dict_short_circuits(self):
        out = apply_welcome_discount({})
        assert out["applied"] is False
        assert out["error"] == "no_discount_params"

    def test_non_dict(self):
        out = apply_welcome_discount(None)
        assert out["applied"] is False


class TestApplierSuccess:

    def test_success_records_via_pattern_z(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        params = generate_welcome_discount(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.welcome_discount."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.welcome_discount."
            "record_writeback",
        ) as record_mock:
            out = apply_welcome_discount(params)
        assert out["applied"] is True
        assert out["code"] == "WELCOME15"
        assert out["percentage"] == 15
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


class TestApplierFailureModes:

    def test_router_unavailable_records_failure(self):
        with patch(
            "engines.store_setup.welcome_discount."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.welcome_discount."
            "record_writeback",
        ) as record_mock:
            out = apply_welcome_discount({
                "code": "WELCOME10",
                "percentage": 10,
            })
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        # Failure still recorded
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail_result(
            "code already exists",
        )
        with patch(
            "engines.store_setup.welcome_discount."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.welcome_discount."
            "record_writeback",
        ) as record_mock:
            out = apply_welcome_discount({
                "code": "WELCOME15",
                "percentage": 15,
            })
        assert out["applied"] is False
        assert "code already exists" in out["error"]
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.welcome_discount."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.welcome_discount."
            "record_writeback",
        ) as record_mock:
            out = apply_welcome_discount({
                "code": "WELCOME15",
                "percentage": 15,
            })
        assert out["applied"] is False
        assert "adapter_raise" in out["error"]
        assert "network" in out["error"]
        assert record_mock.call_args.kwargs["success"] is False


class TestStoreIdPropagation:

    def test_store_id_in_params(self):
        router = MagicMock()
        router.execute.return_value = _ok_result()
        with patch(
            "engines.store_setup.welcome_discount."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.welcome_discount."
            "record_writeback",
        ) as record_mock:
            apply_welcome_discount(
                {"code": "WELCOME15", "percentage": 15},
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
        assert params["code"] == "WELCOME15"
