"""GoogleAdsAdapter -- Google Ads Performance Max + Search.

ShopAI's api-status flagged Google Ads as Tier 1 alongside
Meta Ads. The 5 GOOGLE_ADS_* env vars (developer_token /
client_id / client_secret / refresh_token / customer_id)
were registered in core.adapters.config.ENV_ALIASES but
NO ADAPTER EXISTED. An operator setting all 5 would see
api-status flag ad_channels as satisfied but the router
had no path to route through.

W963-107 ships the skeleton.

Why ship the skeleton now rather than wait for a complete
Google Ads gRPC client:

  * Google Ads API is GRPC-based (not REST) and requires
    the official ``google-ads`` Python SDK + protobuf
    bindings. Adding that dependency tree is a separate
    decision the operator should opt into; the skeleton
    keeps the wiring honest without dragging in 50MB+
    of protobuf code on every install.
  * The skeleton REGISTERS in the bootstrap so api-status
    surfaces "Google Ads adapter wired" once 5 env vars
    arrive. Each capability returns an honest
    AdapterResult.failure pointing the operator to the
    SDK install + the next step.
  * The auth contract (OAuth2 refresh-token exchange) is
    locked in here -- when the operator opts into the
    SDK, only the request/response translation needs to
    fill in, not the configuration plumbing.

Auth model: OAuth2 refresh-token flow (offline access).

  1. Operator generates developer_token from Google Ads
     API Center (one-time, per-MCC).
  2. Operator OAuths into Google Cloud Console -> APIs ->
     Credentials -> OAuth 2.0 Client ID, gets client_id +
     client_secret.
  3. Operator runs a one-time OAuth flow to exchange an
     authorization code for a refresh_token (long-lived).
  4. Each API call exchanges refresh_token -> access_token
     (1-hour TTL).
  5. customer_id identifies which Ads account to operate
     on (the manager-account hierarchy is unsupported in
     this skeleton -- single-account default).

Endpoints (when SDK lands):
  * /v18/customers/{cid}/campaigns:mutate -- create
  * /v18/customers/{cid}/googleAds:searchStream -- query
  * /v18/customers/{cid}/campaignBudgets:mutate -- budget

Reference: https://developers.google.com/google-ads/api/docs
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import (
    AdapterError,
    AdapterNotConfigured,
)
from ._base import AdsBaseAdapter

logger = get_logger("adapters.ads.google_ads")


# Google Ads API base URL (gRPC + REST gateway).
_BASE_URL = "https://googleads.googleapis.com"


class GoogleAdsAdapter(AdsBaseAdapter):
    """Google Ads adapter (skeleton).

    Wired into the bootstrap registry. Each capability
    handler returns a clear "SDK not installed" failure
    until the operator opts into the google-ads dependency.
    """

    name = "google_ads"
    base_url = _BASE_URL
    # Primary credential: developer_token. is_configured()
    # cross-checks the other 4 below.
    config_alias = "google_ads_developer_token"

    # 5 required env vars (per Google Ads OAuth2 contract).
    _DEVELOPER_TOKEN = "google_ads_developer_token"
    _CLIENT_ID = "google_ads_client_id"
    _CLIENT_SECRET = "google_ads_client_secret"
    _REFRESH_TOKEN = "google_ads_refresh_token"
    _CUSTOMER_ID = "google_ads_customer_id"

    # Below Meta Ads (80) because Meta has a simpler 2-key
    # OAuth contract + a complete adapter; operators
    # routing AD_* via the router get Meta by default
    # unless they explicitly opt into Google.
    priority = 70
    cost_per_call = 0.0

    # ── Configuration ─────────────────────────────────────────

    def is_configured(self) -> bool:
        """All 5 env vars must be set for Google Ads to be
        routable. Pre-fix the base class only checked the
        primary config_alias -- partial Google Ads config
        (e.g. developer_token + client_id but no
        refresh_token) would return is_configured=True and
        engines would fail late."""
        cfg = get_config()
        for alias in (
            self._DEVELOPER_TOKEN, self._CLIENT_ID,
            self._CLIENT_SECRET, self._REFRESH_TOKEN,
            self._CUSTOMER_ID,
        ):
            if not cfg.get(alias):
                return False
        return True

    def _credentials(self) -> dict[str, str]:
        """Return the full OAuth2 credential bundle.

        Raises AdapterNotConfigured listing the FIRST
        missing env var so the operator's fix is concrete.
        """
        cfg = get_config()
        out: dict[str, str] = {}
        for alias in (
            self._DEVELOPER_TOKEN, self._CLIENT_ID,
            self._CLIENT_SECRET, self._REFRESH_TOKEN,
            self._CUSTOMER_ID,
        ):
            value = cfg.get(alias)
            if not value:
                env_name = cfg.env_var_for(alias)
                raise AdapterNotConfigured(
                    self.name,
                    f"missing ${env_name or alias}"
                    " -- Google Ads needs all 5 OAuth2 "
                    "credentials (developer_token + "
                    "client_id + client_secret + "
                    "refresh_token + customer_id)",
                )
            out[alias] = value
        return out

    # ── Capability handlers (skeleton) ────────────────────────

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        # Validate the 5 creds before falling back so the
        # error path matches the production path (operator
        # gets configured-ness check first).
        self._credentials()
        return self._not_yet_wired(
            capability,
            "Google Ads campaign create requires the "
            "google-ads Python SDK + protobuf bindings. "
            "Install: pip install google-ads. Then update "
            "GoogleAdsAdapter to dispatch via GoogleAdsClient.",
        )

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._credentials()
        return self._not_yet_wired(
            capability,
            "Google Ads performance query requires the "
            "google-ads SDK. Install: pip install google-ads.",
        )

    def _do_update_budget(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._credentials()
        return self._not_yet_wired(
            capability,
            "Google Ads budget update requires the "
            "google-ads SDK. Install: pip install google-ads.",
        )

    def _do_pause_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._credentials()
        return self._not_yet_wired(
            capability,
            "Google Ads pause requires the google-ads SDK.",
        )

    def _do_resume_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._credentials()
        return self._not_yet_wired(
            capability,
            "Google Ads resume requires the google-ads SDK.",
        )

    # ── Helpers ───────────────────────────────────────────────

    def _not_yet_wired(
        self, capability: Capability, detail: str,
    ) -> AdapterResult:
        """Honest 'configured but not yet operational' path.

        Returns AdapterResult.failure so the router naturally
        falls back to Meta Ads (the default ad-channel
        adapter) when both are configured. Operator sees
        the SDK-install hint via the failure's error field.
        """
        logger.info(
            "Google Ads skeleton called (%s): %s",
            capability.value, detail,
        )
        return AdapterResult.failure(
            adapter=self.name,
            capability=capability.value,
            error=AdapterError(self.name, detail),
        )
