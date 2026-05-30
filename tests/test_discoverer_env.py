"""Tests for core.automation.discoverer_env (W879)."""
from __future__ import annotations

from core.automation.discoverer_env import (
    _normalise,
    resolve_float,
    resolve_int,
)


class TestNormalise:

    def test_dash_to_underscore(self):
        assert _normalise("store-7") == "STORE_7"

    def test_dot_dropped(self):
        assert _normalise("store.acme") == "STOREACME"

    def test_already_clean(self):
        assert _normalise("STORE_X") == "STORE_X"


class TestResolveInt:

    def test_default_when_no_env(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS",
            raising=False,
        )
        v = resolve_int(
            "shipping_alert", "DAYS",
            default=60,
        )
        assert v == 60

    def test_global_env_overrides(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "30",
        )
        v = resolve_int(
            "shipping_alert", "DAYS",
            default=60,
        )
        assert v == 30

    def test_per_store_overrides_global(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "30",
        )
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS_STORE_7",
            "14",
        )
        v = resolve_int(
            "shipping_alert", "DAYS",
            default=60, store_id="store-7",
        )
        # Per-store wins
        assert v == 14
        # Other stores still use global
        v2 = resolve_int(
            "shipping_alert", "DAYS",
            default=60, store_id="store-8",
        )
        assert v2 == 30

    def test_invalid_per_store_falls_back_to_global(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "30",
        )
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS_STORE_7",
            "not-a-number",
        )
        # Invalid per-store -> falls through to global
        v = resolve_int(
            "shipping_alert", "DAYS",
            default=60, store_id="store-7",
        )
        # Per-store env was non-empty -> returned; int parse
        # failed -> default used
        assert v == 60

    def test_min_value_clamps(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "0",
        )
        v = resolve_int(
            "shipping_alert", "DAYS",
            default=60, min_value=1,
        )
        assert v == 1


class TestResolveFloat:

    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_X_DISCOVER_RATIO", raising=False,
        )
        v = resolve_float("x", "RATIO", default=0.5)
        assert v == 0.5

    def test_global_overrides(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_X_DISCOVER_RATIO", "0.75")
        assert resolve_float(
            "x", "RATIO", default=0.5,
        ) == 0.75

    def test_per_store_overrides_global(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_X_DISCOVER_RATIO", "0.5")
        monkeypatch.setenv(
            "SHOPAI_X_DISCOVER_RATIO_STORE_A", "0.9",
        )
        assert resolve_float(
            "x", "RATIO", default=0.0, store_id="store-a",
        ) == 0.9
        assert resolve_float(
            "x", "RATIO", default=0.0, store_id="store-b",
        ) == 0.5

    def test_invalid_returns_default(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_X_DISCOVER_RATIO", "garbage",
        )
        assert resolve_float(
            "x", "RATIO", default=0.5,
        ) == 0.5
