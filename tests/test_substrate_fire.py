"""Tests for core.automation.substrate_fire (Wave 822)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.automation.autonomy_armed import ArmedEntry, ArmedState
from core.automation.payload_discoverer import (
    DiscoveryResult, _DISCOVERERS,
)
from core.automation.substrate_fire import (
    SubstrateFireOutcome,
    SubstrateFireReport,
    fire_armed_substrate_domains,
)


@pytest.fixture(autouse=True)
def _disable_pytest_guards():
    """Disable substrate_fire + autonomy_armed test-env guards
    so the bridge actually runs in tests."""
    state_ref = {"s": ArmedState()}

    def fake_load():
        return ArmedState(entries=list(state_ref["s"].entries))

    def fake_save(s):
        state_ref["s"] = ArmedState(entries=list(s.entries))

    snapshot = dict(_DISCOVERERS)
    _DISCOVERERS.clear()
    with patch(
        "core.automation.substrate_fire."
        "_is_test_environment",
        return_value=False,
    ), patch(
        "core.automation.autonomy_armed._load_state",
        side_effect=fake_load,
    ), patch(
        "core.automation.autonomy_armed._save_state",
        side_effect=fake_save,
    ):
        yield state_ref
    _DISCOVERERS.clear()
    _DISCOVERERS.update(snapshot)


class TestNoArmedDomains:

    def test_returns_empty_report(self, _disable_pytest_guards):
        r = fire_armed_substrate_domains()
        assert r.outcomes == []
        assert r.total_invoked == 0


class TestArmedSubstrateNoDiscoverer:

    def test_skipped_with_no_discoverer_reason(
        self, _disable_pytest_guards,
    ):
        from core.automation.autonomy_armed import arm
        arm("inventory", reason="test")
        # No discoverer registered for inventory
        r = fire_armed_substrate_domains()
        assert len(r.outcomes) == 1
        assert r.outcomes[0].domain == "inventory"
        assert r.outcomes[0].reason == "no_discoverer"
        assert not r.outcomes[0].invoked


class TestArmedSubstrateWithDiscoverer:

    def test_dry_run_when_no_confirm_env(
        self, _disable_pytest_guards, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        from core.automation.payload_discoverer import (
            register_discoverer,
        )
        monkeypatch.delenv(
            "SHOPAI_AUTONOMY_FIRE_CONFIRM", raising=False,
        )
        arm("shipping_alert", reason="test")
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[{"order_id": "x", "tag": "y"}],
                source="test_fixture",
            ),
        )
        r = fire_armed_substrate_domains()
        assert not r.confirm_set
        assert len(r.outcomes) == 1
        assert r.outcomes[0].reason == "dry_run"
        assert r.outcomes[0].discovered == 1
        assert not r.outcomes[0].invoked

    def test_empty_payload_skipped(
        self, _disable_pytest_guards, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        from core.automation.payload_discoverer import (
            register_discoverer,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_FIRE_CONFIRM", "1",
        )
        arm("shipping_alert", reason="test")
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[],
                source="test_fixture",
            ),
        )
        r = fire_armed_substrate_domains()
        assert r.confirm_set
        assert r.outcomes[0].reason == "empty_payload"
        assert r.outcomes[0].discovered == 0

    def test_discoverer_error_captured(
        self, _disable_pytest_guards, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        from core.automation.payload_discoverer import (
            register_discoverer,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_FIRE_CONFIRM", "1",
        )
        arm("shipping_alert", reason="test")

        def busted():
            raise RuntimeError("boom")

        register_discoverer("shipping_alert", busted)
        r = fire_armed_substrate_domains()
        assert r.outcomes[0].reason == "discoverer_error"
        assert "boom" in r.outcomes[0].error

    def test_engine_mode_skipped(
        self, _disable_pytest_guards, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        from core.automation.payload_discoverer import (
            register_discoverer,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_FIRE_CONFIRM", "1",
        )
        # marketing is engine-mode -- skipped even when armed
        arm("marketing", reason="test")
        register_discoverer(
            "marketing",
            lambda: DiscoveryResult(
                domain="marketing",
                payload=[{"k": 1}],
                source="test",
            ),
        )
        r = fire_armed_substrate_domains()
        assert r.outcomes == []


class TestReportDataclass:

    def test_empty_report_aggregates_to_zero(self):
        r = SubstrateFireReport()
        assert r.total_invoked == 0
        assert r.total_discovered_rows == 0

    def test_mixed_outcomes_aggregate(self):
        r = SubstrateFireReport()
        r.outcomes = [
            SubstrateFireOutcome(
                domain="a", discovered=3, invoked=True,
            ),
            SubstrateFireOutcome(
                domain="b", discovered=2, invoked=False,
            ),
            SubstrateFireOutcome(
                domain="c", discovered=5, invoked=True,
            ),
        ]
        assert r.total_invoked == 2
        assert r.total_discovered_rows == 10
