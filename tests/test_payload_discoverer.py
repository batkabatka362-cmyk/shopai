"""Tests for core.automation.payload_discoverer (Wave 820)."""
from __future__ import annotations

import pytest

from core.automation.payload_discoverer import (
    DiscoveryResult,
    _DISCOVERERS,
    discover,
    discover_all_armed_substrate,
    has_discoverer,
    register_discoverer,
    registered_domains,
    unregister_discoverer,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test starts with a clean registry."""
    snapshot = dict(_DISCOVERERS)
    _DISCOVERERS.clear()
    yield
    _DISCOVERERS.clear()
    _DISCOVERERS.update(snapshot)


class TestDiscoveryResult:

    def test_defaults(self):
        r = DiscoveryResult(domain="x")
        assert r.payload == []
        assert r.source == ""
        assert r.error == ""
        assert r.ok
        assert r.payload_size == 0
        assert r.discovered_at > 0

    def test_payload_size(self):
        r = DiscoveryResult(
            domain="x",
            payload=[{"a": 1}, {"b": 2}, {"c": 3}],
        )
        assert r.payload_size == 3

    def test_not_ok_with_error(self):
        r = DiscoveryResult(domain="x", error="boom")
        assert not r.ok


class TestRegistry:

    def test_empty_registry(self):
        assert registered_domains() == []
        assert not has_discoverer("shipping_alert")

    def test_register_then_lookup(self):
        def fake():
            return DiscoveryResult(
                domain="shipping_alert",
                payload=[{"order_id": "x"}],
                source="fake",
            )
        register_discoverer("shipping_alert", fake)
        assert has_discoverer("shipping_alert")
        assert registered_domains() == ["shipping_alert"]

    def test_register_unknown_domain_raises(self):
        with pytest.raises(ValueError) as exc_info:
            register_discoverer(
                "totally_bogus_name",
                lambda: DiscoveryResult(domain="x"),
            )
        assert "unknown autonomy domain" in str(exc_info.value)

    def test_unregister(self):
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(domain="shipping_alert"),
        )
        assert unregister_discoverer("shipping_alert")
        assert not has_discoverer("shipping_alert")

    def test_unregister_missing_returns_false(self):
        assert not unregister_discoverer("shipping_alert")

    def test_re_register_replaces(self):
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert", source="v1",
            ),
        )
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert", source="v2",
            ),
        )
        assert discover("shipping_alert").source == "v2"


class TestDiscover:

    def test_unregistered_returns_error(self):
        r = discover("inventory")
        assert not r.ok
        assert "no discoverer registered" in r.error

    def test_registered_runs(self):
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[{"order_id": "gid://test/1"}],
                source="test_fixture",
            ),
        )
        r = discover("shipping_alert")
        assert r.ok
        assert r.payload_size == 1
        assert r.source == "test_fixture"

    def test_discoverer_raise_captured(self):
        def explode():
            raise RuntimeError("boom")
        register_discoverer("shipping_alert", explode)
        r = discover("shipping_alert")
        assert not r.ok
        assert "discoverer raised" in r.error
        assert "boom" in r.error

    def test_discoverer_returns_wrong_type(self):
        register_discoverer(
            "shipping_alert",
            lambda: "not a DiscoveryResult",
        )
        r = discover("shipping_alert")
        assert not r.ok
        assert "non-DiscoveryResult" in r.error

    def test_discoverer_returns_non_list_payload(self):
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload="not a list",  # type: ignore
            ),
        )
        r = discover("shipping_alert")
        assert not r.ok
        assert "must be list" in r.error

    def test_discoverer_returns_non_dict_row(self):
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[{"ok": 1}, "broken"],  # type: ignore
            ),
        )
        r = discover("shipping_alert")
        assert not r.ok
        assert "payload[1]" in r.error
        assert "must be dict" in r.error


class TestDiscoverAllArmedSubstrate:

    def test_empty_when_nothing_armed(self):
        # Even with registered discoverers, if nothing is armed
        # we get an empty list.
        register_discoverer(
            "shipping_alert",
            lambda: DiscoveryResult(
                domain="shipping_alert",
                payload=[{"order_id": "x"}],
            ),
        )
        # Note: autonomy_armed uses Pattern J test guard so
        # the file write no-ops; but list_armed reads the
        # JSON which doesn't exist in tests -> returns empty.
        results = discover_all_armed_substrate()
        assert results == []
