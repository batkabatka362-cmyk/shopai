"""W963-116: per-store credential helper + Meta Ads adoption."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.adapters._per_store_credentials import (
    _normalise_sid_for_env,
    _per_store_env_var,
    has_per_store,
    resolve_per_store,
)


# ── Sid normalisation ─────────────────────────────────────


class TestNormaliseSid:
    def test_lowercase_to_upper(self):
        assert _normalise_sid_for_env("store_a") == "STORE_A"

    def test_hyphen_to_underscore(self):
        assert _normalise_sid_for_env("store-a") == "STORE_A"

    def test_mixed(self):
        assert (
            _normalise_sid_for_env("my-shop-2")
            == "MY_SHOP_2"
        )

    def test_empty(self):
        assert _normalise_sid_for_env("") == ""


class TestPerStoreEnvVarBuilder:
    def test_builds_canonical_name(self):
        assert _per_store_env_var(
            "store_a", "META_ADS_ACCESS_TOKEN",
        ) == "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN"

    def test_empty_sid_returns_empty(self):
        assert _per_store_env_var(
            "", "META_ADS_ACCESS_TOKEN",
        ) == ""

    def test_empty_env_name_returns_empty(self):
        assert _per_store_env_var("store_a", "") == ""


# ── resolve_per_store ─────────────────────────────────────


class TestResolvePerStore:
    """The core helper. Resolution chain:
      1. Per-store env var (SHOPAI_STORE_<SID>_<ALIAS>)
      2. Fleet-wide env var (canonical name from
         AdapterConfig.env_var_for)
      3. default param
    """

    def _reset_singletons(self):
        """The AdapterConfig is a process-wide singleton
        that caches env vars at construction. Reset it so
        each test sees the patched environment."""
        from core.adapters.config import reset_config
        reset_config()

    def test_per_store_env_var_wins(self, monkeypatch):
        from core.context import active_store
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_default",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            "store_a_specific",
        )
        self._reset_singletons()
        with active_store("store_a"):
            assert resolve_per_store(
                "meta_ads_access_token"
            ) == "store_a_specific"

    def test_fleet_fallback_when_no_per_store(
        self, monkeypatch,
    ):
        from core.context import active_store
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_default",
        )
        monkeypatch.delenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            raising=False,
        )
        self._reset_singletons()
        with active_store("store_a"):
            assert resolve_per_store(
                "meta_ads_access_token"
            ) == "fleet_default"

    def test_no_active_store_uses_fleet(self, monkeypatch):
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_default",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            "store_a_value",
        )
        self._reset_singletons()
        # No active_store wrap; per-store ignored
        assert resolve_per_store(
            "meta_ads_access_token"
        ) == "fleet_default"

    def test_empty_returns_default(self, monkeypatch):
        from core.context import active_store
        monkeypatch.delenv(
            "META_ADS_ACCESS_TOKEN", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            raising=False,
        )
        self._reset_singletons()
        with active_store("store_a"):
            result = resolve_per_store(
                "meta_ads_access_token",
                default="fallback_value",
            )
        assert result == "fallback_value"

    def test_unknown_alias_returns_default(self):
        assert resolve_per_store(
            "totally_made_up_alias",
            default="fallback",
        ) == "fallback"

    def test_hyphen_sid_normalises_correctly(
        self, monkeypatch,
    ):
        """store_id with hyphens ('store-a') maps to
        env var SHOPAI_STORE_STORE_A_..."""
        from core.context import active_store
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            "store_a_value",
        )
        self._reset_singletons()
        # Operator-side store_id "store-a" matches env
        # SHOPAI_STORE_STORE_A_...
        with active_store("store-a"):
            assert resolve_per_store(
                "meta_ads_access_token"
            ) == "store_a_value"


class TestHasPerStore:
    def test_true_when_resolved(self, monkeypatch):
        from core.adapters.config import reset_config
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "x",
        )
        reset_config()
        assert has_per_store("meta_ads_access_token") is True

    def test_false_when_empty(self, monkeypatch):
        from core.adapters.config import reset_config
        monkeypatch.delenv(
            "META_ADS_ACCESS_TOKEN", raising=False,
        )
        reset_config()
        assert has_per_store("meta_ads_access_token") is False


# ── Meta Ads adapter adoption ─────────────────────────────


class TestMetaAdsPerStore:
    """W963-116: Meta Ads adapter resolves access token +
    ad account ID per-store when active_store is set."""

    def _reset_singletons(self):
        from core.adapters.config import reset_config
        reset_config()

    def test_meta_ads_account_id_per_store(
        self, monkeypatch,
    ):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        from core.context import active_store

        # Fleet defaults
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_token",
        )
        monkeypatch.setenv(
            "META_ADS_ACCOUNT_ID", "act_000",
        )
        # Per-store override
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            "store_a_token",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCOUNT_ID",
            "act_111",
        )
        self._reset_singletons()

        a = MetaAdsAdapter()
        # Without active_store -> fleet
        assert a._account_id() == "act_000"

        # With active_store -> per-store
        with active_store("store_a"):
            assert a._account_id() == "act_111"

    def test_meta_ads_access_token_per_store(
        self, monkeypatch,
    ):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        from core.context import active_store

        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_token",
        )
        monkeypatch.setenv(
            "META_ADS_ACCOUNT_ID", "act_000",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_META_ADS_ACCESS_TOKEN",
            "store_b_token",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_META_ADS_ACCOUNT_ID",
            "act_222",
        )
        self._reset_singletons()

        a = MetaAdsAdapter()
        with active_store("store_b"):
            headers = a._auth_headers()
        assert headers["Authorization"] == (
            "Bearer store_b_token"
        )

    def test_meta_ads_is_configured_honours_per_store(
        self, monkeypatch,
    ):
        """When fleet creds are missing but per-store creds
        are set, is_configured returns True under
        active_store(sid)."""
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        from core.context import active_store

        monkeypatch.delenv(
            "META_ADS_ACCESS_TOKEN", raising=False,
        )
        monkeypatch.delenv(
            "META_ADS_ACCOUNT_ID", raising=False,
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN",
            "store_a_token",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCOUNT_ID",
            "act_111",
        )
        self._reset_singletons()

        a = MetaAdsAdapter()
        # No active_store -> not configured (no fleet creds)
        assert a.is_configured() is False

        # active_store -> configured
        with active_store("store_a"):
            assert a.is_configured() is True

    def test_meta_ads_falls_back_to_fleet_when_no_override(
        self, monkeypatch,
    ):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        from core.context import active_store

        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "fleet_token",
        )
        monkeypatch.setenv(
            "META_ADS_ACCOUNT_ID", "act_000",
        )
        self._reset_singletons()

        a = MetaAdsAdapter()
        # Active store "store_c" has NO per-store override
        # -> falls back to fleet defaults (no crash)
        with active_store("store_c"):
            assert a._account_id() == "act_000"
            headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer fleet_token"
