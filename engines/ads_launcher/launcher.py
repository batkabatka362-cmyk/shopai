"""First-campaign launcher.

Operator-facing wrapper around ADS_CREATE_CAMPAIGN that:

  1. Resolves the platform's adapter via SmartRouter
  2. Generates a sensible campaign config from operator input
     (name auto-derived from niche + date if not supplied)
  3. Creates the campaign with status=PAUSED (always — operator
     activates in platform UI)
  4. Returns campaign_id + the URL operator should visit next
  5. Records via Pattern Z (record_writeback) so the autonomous
     loop sees the action

The launcher never enables a campaign autonomously. PAUSED status
is the safety gate — the operator must explicitly activate it in
Meta/Google Ads Manager, which forces them to:
  - Add ad sets + creatives + audience targeting
  - Review the budget config the engine generated
  - Make the conscious "spend real money" decision
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


_ENGINE = "ads_launcher"
_ACTION_TYPE = "launch_first_campaign"


# Default Meta Ads objectives keyed by what we infer from the
# operator's input. SALES is the right default for e-commerce.
_DEFAULT_META_OBJECTIVE = "OUTCOME_SALES"
_DEFAULT_GOOGLE_OBJECTIVE = "SALES"

# Conservative defaults — small budget, PAUSED start.
_DEFAULT_DAILY_USD = 10.0
_MAX_DAILY_USD = 1000.0


@dataclass
class LaunchResult:
    platform: str
    success: bool
    campaign_id: str = ""
    campaign_name: str = ""
    daily_budget_usd: float = 0.0
    status: str = "PAUSED"
    next_url: str = ""
    error: str = ""


def _platform_objective(platform: str) -> str:
    if platform == "meta":
        return _DEFAULT_META_OBJECTIVE
    if platform == "google":
        return _DEFAULT_GOOGLE_OBJECTIVE
    return "SALES"


def _platform_next_url(
    platform: str, campaign_id: str,
) -> str:
    """The Manager URL the operator should visit after launch
    to add creative + activate."""
    if platform == "meta":
        return (
            "https://business.facebook.com/adsmanager/manage/"
            f"campaigns?selected_campaign_ids={campaign_id}"
        )
    if platform == "google":
        return (
            "https://ads.google.com/aw/campaigns"
            f"?campaignId={campaign_id}"
        )
    return ""


def _default_campaign_name(niche: str | None) -> str:
    """ShopAI-<niche>-YYYY-MM-DD format. Auto-uniqueness via
    date + niche."""
    niche_slug = (niche or "general").lower().strip()[:20]
    date_str = time.strftime("%Y%m%d", time.gmtime())
    return f"ShopAI-{niche_slug}-{date_str}"


def launch_first_campaign(
    *,
    platform: str,
    daily_budget_usd: float = _DEFAULT_DAILY_USD,
    name: str | None = None,
    niche: str | None = None,
    objective: str | None = None,
    record_writeback: bool = True,
) -> LaunchResult:
    """Fire the first PAUSED campaign on the given platform.

    Validates budget bounds (1 USD <= budget <= 1000 USD/day).
    Generates a sensible name + objective if not supplied.
    Always creates PAUSED — operator activates in platform UI.

    Returns a structured result. Records via record_writeback
    by default; pass False for dry-run / preview-only flows."""
    platform = (platform or "").lower()
    if platform not in ("meta", "google"):
        return LaunchResult(
            platform=platform, success=False,
            error=(
                f"unsupported platform '{platform}'. Use "
                "meta or google."
            ),
        )

    try:
        budget = float(daily_budget_usd)
    except (TypeError, ValueError):
        return LaunchResult(
            platform=platform, success=False,
            error="daily_budget_usd must be numeric",
        )
    if budget < 1.0:
        return LaunchResult(
            platform=platform, success=False,
            error="daily_budget_usd must be >= 1.0",
        )
    if budget > _MAX_DAILY_USD:
        return LaunchResult(
            platform=platform, success=False,
            error=(
                f"daily_budget_usd must be <= "
                f"{_MAX_DAILY_USD:.0f} (safety cap). For "
                "higher budgets, edit the campaign in the "
                "platform Manager after launch."
            ),
        )

    campaign_name = name or _default_campaign_name(niche)
    obj = objective or _platform_objective(platform)
    # Adapter expects cents for daily_budget on Meta.
    # W962-71 rounding to nearest cent.
    daily_budget_cents = int(round(budget * 100))

    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        return LaunchResult(
            platform=platform, success=False,
            error=f"router unavailable: {type(exc).__name__}",
        )

    params = {
        "name": campaign_name,
        "objective": obj,
        "status": "PAUSED",  # ALWAYS PAUSED at creation
        "daily_budget": daily_budget_cents,
    }

    try:
        result = router.execute(
            Capability.ADS_CREATE_CAMPAIGN, params,
        )
    except Exception as exc:  # noqa: BLE001
        return LaunchResult(
            platform=platform, success=False,
            error=f"adapter raised: {type(exc).__name__}: {exc}",
        )

    ok = bool(getattr(result, "ok", False))
    err = getattr(result, "error", "") or ""
    data = getattr(result, "data", None) or {}
    campaign_id = ""
    if isinstance(data, dict):
        campaign_id = str(
            data.get("campaign_id") or data.get("id") or ""
        )

    if record_writeback:
        try:
            from engines._writeback_recorder import (
                record_writeback as _rwb,
            )
            _rwb(
                engine=_ENGINE,
                action_type=_ACTION_TYPE,
                capability="ADS_CREATE_CAMPAIGN",
                params=params,
                success=ok,
                error=None if ok else err,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "ads_launcher writeback raised: %s", exc,
            )

    if not ok:
        return LaunchResult(
            platform=platform, success=False,
            campaign_name=campaign_name,
            daily_budget_usd=round(budget, 2),
            error=err or "campaign creation failed",
        )

    return LaunchResult(
        platform=platform, success=True,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        daily_budget_usd=round(budget, 2),
        status="PAUSED",
        next_url=_platform_next_url(platform, campaign_id),
    )
