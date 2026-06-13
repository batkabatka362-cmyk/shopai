"""Tests for GoogleAdsAdapter -- W963-107."""
from __future__ import annotations

from unittest.mock import patch

from core.adapters.base import Capability
from core.adapters.errors import AdapterNotConfigured
from core.adapters.ads.google_ads import GoogleAdsAdapter


_FULL_CREDS = {
    "google_ads_developer_token": "dev-token",
    "google_ads_client_id": "client-id",
    "google_ads_client_secret": "client-secret",
    "google_ads_refresh_token": "refresh-token",
    "google_ads_customer_id": "123-456-7890",
}


def _cfg_with(creds: dict) -> object:
    """Build a mock get_config().get that returns from a dict."""
    class _Fake:
        def get(self, alias, default=""):
            return creds.get(alias, "")
        def env_var_for(self, alias):
            mapping = {
                "google_ads_developer_token":
                    "GOOGLE_ADS_DEVELOPER_TOKEN",
                "google_ads_client_id":
                    "GOOGLE_ADS_CLIENT_ID",
                "google_ads_client_secret":
                    "GOOGLE_ADS_CLIENT_SECRET",
                "google_ads_refresh_token":
                    "GOOGLE_ADS_REFRESH_TOKEN",
                "google_ads_customer_id":
                    "GOOGLE_ADS_CUSTOMER_ID",
            }
            return mapping.get(alias, "")
    return _Fake()


# ── Configuration ─────────────────────────────────────────


class TestGoogleAdsConfiguration:
    def test_is_configured_false_when_all_missing(self):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with({}),
        ):
            adapter = GoogleAdsAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_false_with_partial_creds(self):
        """Pre-fix bug class: base class only checked the
        primary config_alias, so 1-of-5 creds returned True.
        Post-fix: ALL 5 must be set."""
        for missing_key in _FULL_CREDS:
            partial = {
                k: v for k, v in _FULL_CREDS.items()
                if k != missing_key
            }
            with patch(
                "core.adapters.ads.google_ads.get_config",
                return_value=_cfg_with(partial),
            ):
                adapter = GoogleAdsAdapter()
                assert adapter.is_configured() is False, (
                    f"is_configured should be False with "
                    f"{missing_key} missing"
                )

    def test_is_configured_true_when_all_5_set(self):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            assert adapter.is_configured() is True


# ── Credential resolution ──────────────────────────────────


class TestGoogleAdsCredentials:
    def test_credentials_returns_all_5(self):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            creds = adapter._credentials()
            assert len(creds) == 5
            assert all(
                creds[k] == v for k, v in _FULL_CREDS.items()
            )

    def test_credentials_raises_with_clear_message_on_missing(
        self,
    ):
        partial = {
            "google_ads_developer_token": "dev",
            # client_id missing
            "google_ads_client_secret": "x",
            "google_ads_refresh_token": "y",
            "google_ads_customer_id": "z",
        }
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(partial),
        ):
            adapter = GoogleAdsAdapter()
            try:
                adapter._credentials()
                raise AssertionError("expected raise")
            except AdapterNotConfigured as exc:
                # Error names the missing env var so
                # operator can copy/paste
                assert "GOOGLE_ADS_CLIENT_ID" in str(exc)


# ── Metadata ───────────────────────────────────────────────


class TestGoogleAdsMetadata:
    def test_name(self):
        assert GoogleAdsAdapter.name == "google_ads"

    def test_priority_below_meta_ads(self):
        """Meta has a complete adapter; Google Ads is
        skeleton. Router picks Meta by default when both
        configured."""
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        assert (
            GoogleAdsAdapter.priority < MetaAdsAdapter.priority
        )

    def test_capabilities_cover_full_ad_lifecycle(self):
        caps = GoogleAdsAdapter.capabilities
        assert Capability.ADS_CREATE_CAMPAIGN in caps
        assert Capability.ADS_GET_PERFORMANCE in caps
        assert Capability.ADS_UPDATE_BUDGET in caps
        assert Capability.ADS_PAUSE_CAMPAIGN in caps
        assert Capability.ADS_RESUME_CAMPAIGN in caps


# ── Dispatch ───────────────────────────────────────────────


class TestGoogleAdsDispatch:
    """Skeleton handlers return not-yet-wired failures so the
    router naturally falls back to Meta Ads. Each handler
    runs the credentials check FIRST."""

    def test_create_campaign_without_creds_raises_not_configured(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with({}),
        ):
            adapter = GoogleAdsAdapter()
            try:
                adapter._do_create_campaign(
                    Capability.ADS_CREATE_CAMPAIGN,
                    {"name": "x"},
                )
                raise AssertionError(
                    "expected AdapterNotConfigured"
                )
            except AdapterNotConfigured:
                pass

    def test_create_campaign_with_creds_returns_not_wired(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            result = adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x"},
            )
            assert result.ok is False
            assert "google-ads" in str(result.error).lower()
            assert "sdk" in str(result.error).lower()

    def test_get_performance_returns_not_wired_with_creds(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            result = adapter._do_get_performance(
                Capability.ADS_GET_PERFORMANCE, {},
            )
            assert result.ok is False

    def test_update_budget_returns_not_wired_with_creds(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            result = adapter._do_update_budget(
                Capability.ADS_UPDATE_BUDGET, {},
            )
            assert result.ok is False

    def test_pause_campaign_returns_not_wired_with_creds(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            result = adapter._do_pause_campaign(
                Capability.ADS_PAUSE_CAMPAIGN, {},
            )
            assert result.ok is False

    def test_resume_campaign_returns_not_wired_with_creds(
        self,
    ):
        with patch(
            "core.adapters.ads.google_ads.get_config",
            return_value=_cfg_with(_FULL_CREDS),
        ):
            adapter = GoogleAdsAdapter()
            result = adapter._do_resume_campaign(
                Capability.ADS_RESUME_CAMPAIGN, {},
            )
            assert result.ok is False


# ── Bootstrap registration ─────────────────────────────────


class TestGoogleAdsBootstrap:
    def test_register_all_includes_google_ads(self):
        from core.adapters.ads.bootstrap import (
            _ADS_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _ADS_ADAPTER_CLASSES]
        assert "google_ads" in names
        assert "meta_ads" in names
