"""Tests for thrash guardrail (Wave 915)."""
from __future__ import annotations

from unittest.mock import patch

from engines._agi_context import (
    explain_thrash_block,
    should_block_thrashing_store,
    thrash_guardrail_enabled,
)


class TestEnabled:

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        assert not thrash_guardrail_enabled()

    def test_truthy_on(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        assert thrash_guardrail_enabled()

    def test_other_truthy(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "true")
        assert thrash_guardrail_enabled()


class TestShouldBlock:

    def test_disabled_returns_false(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        assert not should_block_thrashing_store("store-7")

    def test_no_store_returns_false(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        assert not should_block_thrashing_store(None)
        assert not should_block_thrashing_store("")

    def test_blocks_when_thrashing(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "thrashing"})()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ):
            assert should_block_thrashing_store("store-7")

    def test_allows_when_calm(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "calm"})()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ):
            assert not should_block_thrashing_store("store-7")

    def test_allows_when_elevated(self, monkeypatch):
        # Elevated is a warning, not a hard block
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "elevated"})()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ):
            assert not should_block_thrashing_store("store-7")

    def test_probe_failure_does_not_block(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            side_effect=RuntimeError("probe broken"),
        ):
            assert not should_block_thrashing_store("store-7")


class TestExplainBlock:

    def test_carries_store_id(self):
        msg = explain_thrash_block("store-7")
        assert "store=store-7" in msg
        assert "thrashing" in msg

    def test_handles_none(self):
        msg = explain_thrash_block(None)
        assert "store=fleet" in msg
