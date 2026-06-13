"""Tests for per-store thrash guardrail (Wave 925)."""
from __future__ import annotations

from unittest.mock import patch

from engines._agi_context import (
    should_block_thrashing_store,
    thrash_guardrail_enabled,
)


class TestEnabledPerStore:

    def test_fleet_off_per_store_on(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_THRASH_GUARDRAIL", False,
        )
        monkeypatch.setenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", "1",
        )
        assert thrash_guardrail_enabled("store-7")
        # Other stores still off
        assert not thrash_guardrail_enabled("store-8")
        # No store_id falls through to fleet (off)
        assert not thrash_guardrail_enabled()

    def test_fleet_on_per_store_off_overrides(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        monkeypatch.setenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", "0",
        )
        # store-7 explicitly off despite fleet on
        assert not thrash_guardrail_enabled("store-7")
        # store-8 follows fleet
        assert thrash_guardrail_enabled("store-8")

    def test_empty_per_store_falls_through(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        monkeypatch.delenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", False,
        )
        # No per-store override; uses fleet
        assert thrash_guardrail_enabled("store-7")

    def test_normalisation_hyphens(self, monkeypatch):
        # "store-7" -> SHOPAI_..._STORE_7 (hyphen to under)
        monkeypatch.delenv(
            "SHOPAI_THRASH_GUARDRAIL", False,
        )
        monkeypatch.setenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", "1",
        )
        assert thrash_guardrail_enabled("store-7")
        assert thrash_guardrail_enabled("STORE-7")


class TestShouldBlockPerStore:

    def test_per_store_on_blocks(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_THRASH_GUARDRAIL", False,
        )
        monkeypatch.setenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", "1",
        )
        fake_rep = type("R", (), {"verdict": "thrashing"})()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ):
            assert should_block_thrashing_store("store-7")
            # Other store: fleet off + no per-store override
            assert not should_block_thrashing_store("store-8")

    def test_per_store_off_unblocks_despite_fleet_on(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        monkeypatch.setenv(
            "SHOPAI_THRASH_GUARDRAIL_STORE_7", "0",
        )
        fake_rep = type("R", (), {"verdict": "thrashing"})()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ):
            # store-7 force-off via per-store override
            assert not should_block_thrashing_store("store-7")
            # store-8 follows fleet on -> blocks
            assert should_block_thrashing_store("store-8")
