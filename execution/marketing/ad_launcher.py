"""AdLauncher — launches ad campaigns on Facebook, Google, and TikTok.

Uses only the Python standard library.  Platform API calls are performed
via ``urllib.request``; optional third-party SDKs are imported lazily but
never required.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Platform-specific required config fields
# ---------------------------------------------------------------------------
_PLATFORM_REQUIRED: dict[str, list[str]] = {
    "facebook": ["name", "objective", "budget_amount", "start_time"],
    "google": ["name", "budget_amount", "bidding_strategy"],
    "tiktok": ["name", "objective", "budget_amount", "start_time"],
}

_PLATFORM_API_VERSIONS = {
    "facebook": "v19.0",
    "google": "v14",
    "tiktok": "v1.3",
}


class AdLauncher:
    """Launches ad campaigns on Facebook Ads, Google Ads, and TikTok Ads."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def launch_facebook_ad(
        self,
        account_id: str,
        access_token: str,
        campaign_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a Facebook Ads campaign via the Graph API.

        Args:
            account_id:      Facebook Ads account ID (``act_<id>`` format).
            access_token:    Facebook user/app access token.
            campaign_config: Campaign parameters (name, objective,
                             budget_amount, start_time, …).

        Returns:
            Normalised response dict with keys: platform, campaign_id,
            status, created_at.
        """
        errors = self._validate_campaign_config(campaign_config, "facebook")
        if errors:
            return {"status": "error", "errors": errors, "platform": "facebook"}

        version = _PLATFORM_API_VERSIONS["facebook"]
        act_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
        url = f"https://graph.facebook.com/{version}/{act_id}/campaigns"

        payload: dict[str, Any] = {
            "name": campaign_config["name"],
            "objective": campaign_config.get("objective", "OUTCOME_TRAFFIC"),
            "status": campaign_config.get("status", "PAUSED"),
            "special_ad_categories": campaign_config.get("special_ad_categories", []),
            "daily_budget": int(float(campaign_config["budget_amount"]) * 100),
            "access_token": access_token,
        }
        if "start_time" in campaign_config:
            payload["start_time"] = campaign_config["start_time"]

        try:
            raw = self._make_api_request("POST", url, {}, payload, use_form=True)
            return self._normalize_response("facebook", raw)
        except Exception as exc:
            return {"status": "error", "platform": "facebook", "error": str(exc)}

    def launch_google_ad(
        self,
        customer_id: str,
        credentials: dict[str, Any],
        campaign_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a Google Ads campaign via the Google Ads REST API.

        Args:
            customer_id:  Google Ads customer ID (digits only).
            credentials:  Dict with ``developer_token`` and ``access_token``.
            campaign_config: Campaign parameters (name, budget_amount,
                             bidding_strategy, …).

        Returns:
            Normalised response dict.
        """
        errors = self._validate_campaign_config(campaign_config, "google")
        if errors:
            return {"status": "error", "errors": errors, "platform": "google"}

        cid = customer_id.replace("-", "")
        url = (
            f"https://googleads.googleapis.com/v14/customers/{cid}/campaigns:mutate"
        )
        headers = {
            "Authorization": f"Bearer {credentials.get('access_token', '')}",
            "developer-token": credentials.get("developer_token", ""),
            "Content-Type": "application/json",
        }
        if "login_customer_id" in credentials:
            headers["login-customer-id"] = str(credentials["login_customer_id"])

        budget_micros = int(float(campaign_config["budget_amount"]) * 1_000_000)
        operation = {
            "create": {
                "name": campaign_config["name"],
                "status": campaign_config.get("status", "PAUSED"),
                "advertisingChannelType": campaign_config.get(
                    "advertising_channel_type", "SEARCH"
                ),
                "manualCpc": {},
                "campaignBudget": {
                    "amountMicros": str(budget_micros),
                    "deliveryMethod": "STANDARD",
                },
            }
        }
        if campaign_config.get("bidding_strategy") == "TARGET_CPA":
            del operation["create"]["manualCpc"]
            operation["create"]["targetCpa"] = {
                "targetCpaMicros": str(
                    int(float(campaign_config.get("target_cpa", 10)) * 1_000_000)
                )
            }

        payload = {"operations": [operation]}

        try:
            raw = self._make_api_request("POST", url, headers, payload)
            return self._normalize_response("google", raw)
        except Exception as exc:
            return {"status": "error", "platform": "google", "error": str(exc)}

    def launch_tiktok_ad(
        self,
        advertiser_id: str,
        access_token: str,
        campaign_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a TikTok Ads campaign via the Marketing API.

        Args:
            advertiser_id: TikTok advertiser account ID.
            access_token:  TikTok Marketing API access token.
            campaign_config: Campaign parameters (name, objective,
                             budget_amount, start_time, …).

        Returns:
            Normalised response dict.
        """
        errors = self._validate_campaign_config(campaign_config, "tiktok")
        if errors:
            return {"status": "error", "errors": errors, "platform": "tiktok"}

        version = _PLATFORM_API_VERSIONS["tiktok"]
        url = f"https://business-api.tiktok.com/open_api/{version}/campaign/create/"
        headers = {
            "Access-Token": access_token,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "campaign_name": campaign_config["name"],
            "objective_type": campaign_config.get("objective", "TRAFFIC"),
            "budget_mode": campaign_config.get("budget_mode", "BUDGET_MODE_DAY"),
            "budget": float(campaign_config["budget_amount"]),
        }
        if "start_time" in campaign_config:
            payload["start_time"] = campaign_config["start_time"]
        if "end_time" in campaign_config:
            payload["end_time"] = campaign_config["end_time"]

        try:
            raw = self._make_api_request("POST", url, headers, payload)
            return self._normalize_response("tiktok", raw)
        except Exception as exc:
            return {"status": "error", "platform": "tiktok", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _validate_campaign_config(
        self, config: dict[str, Any], platform: str
    ) -> list[str]:
        """Return list of validation errors for *config* on *platform*."""
        required = _PLATFORM_REQUIRED.get(platform, [])
        errors: list[str] = []
        for field in required:
            if field not in config or config[field] in (None, ""):
                errors.append(f"Missing required field for {platform}: '{field}'")
        budget = config.get("budget_amount")
        if budget is not None:
            try:
                if float(budget) <= 0:
                    errors.append("'budget_amount' must be a positive number.")
            except (TypeError, ValueError):
                errors.append("'budget_amount' must be numeric.")
        return errors

    def _normalize_response(
        self, platform: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        """Map a raw platform API response to a common envelope.

        Returns:
            ``{"platform": str, "campaign_id": str, "status": str,
               "created_at": str, "raw": {...}}``
        """
        now = datetime.now(timezone.utc).isoformat()

        if platform == "facebook":
            campaign_id = str(response.get("id", ""))
            api_status = "active" if campaign_id else "error"
        elif platform == "google":
            results = response.get("results", [{}])
            resource_name = results[0].get("resourceName", "") if results else ""
            campaign_id = resource_name.split("/")[-1] if resource_name else ""
            api_status = "active" if campaign_id else "error"
        elif platform == "tiktok":
            data = response.get("data", {})
            campaign_id = str(data.get("campaign_id", ""))
            code = response.get("code", -1)
            api_status = "active" if code == 0 else "error"
        else:
            campaign_id = str(response.get("id", response.get("campaign_id", "")))
            api_status = response.get("status", "unknown")

        return {
            "platform": platform,
            "campaign_id": campaign_id,
            "status": api_status,
            "created_at": now,
            "raw": response,
        }

    def _make_api_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        use_form: bool = False,
    ) -> dict[str, Any]:
        """Perform an HTTP request, handling 429 with retry."""
        data: bytes | None = None
        if payload is not None:
            if use_form:
                data = urllib.parse.urlencode(payload).encode("utf-8")
                headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
            else:
                data = json.dumps(payload).encode("utf-8")
                headers = {**headers, "Content-Type": "application/json"}

        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    retry_after = float(exc.headers.get("Retry-After", delay))
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise urllib.error.HTTPError(
                    url, exc.code, f"{exc.reason} — {body}", exc.headers, None
                ) from exc
            except urllib.error.URLError:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

        raise RuntimeError(f"Request to {url} failed after {max_retries} retries.")
