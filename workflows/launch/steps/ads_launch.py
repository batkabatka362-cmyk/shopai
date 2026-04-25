"""Step 7 — Meta Ads campaign launch.

Wire the variants from ``creative`` into a Meta Ads campaign with the
budget + audience the owner specified. Uses the Meta Ads adapter at
``core/adapters/ads/meta_ads.py``.

Required env vars (must be set before this step runs):
    META_ADS_ACCESS_TOKEN
    META_ADS_ACCOUNT_ID       (act_1234567890)
    META_ADS_PIXEL_ID         (for conversion tracking)
    META_ADS_PAGE_ID          (FB page the ad is run as)
"""
from __future__ import annotations

import os
from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


REQUIRED_ENV = ("META_ADS_ACCESS_TOKEN", "META_ADS_ACCOUNT_ID", "META_ADS_PIXEL_ID", "META_ADS_PAGE_ID")


class AdsLaunchStep(Step):
    name = "ads_launch"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
        if missing:
            raise StepSkip(f"Meta Ads not configured (missing {', '.join(missing)})")

        if not context.shopify_product.get("storefront_url"):
            raise StepSkip("no Shopify storefront URL — nothing to advertise")

        if not context.creative.get("variants"):
            raise StepSkip("no creative variants — run creative step first")

        # Live-execution gate (§4b.G paranoid mode). Same gate
        # publisher_bundle + campaign_activator consult — keeps
        # every write path agreeing on "are we actually
        # spending money?". If off, campaign is staged as
        # PAUSED so the owner can review before flipping active.
        from core.system.live_execution import (
            is_live_execution_enabled,
        )
        live = is_live_execution_enabled()

        from core.adapters.base import Capability
        from core.adapters.ads.meta_ads import MetaAdsAdapter

        adapter = MetaAdsAdapter()
        if not adapter.is_configured():
            raise StepSkip(
                "Meta Ads adapter not configured "
                "(env vars present but adapter rejected)",
            )

        launch_id = context.launch_id
        # Meta expects budget in cents (account currency minor
        # unit). ad_budget_day=20.0 USD → 2000 cents.
        daily_budget_cents = int(
            round(float(context.goal.ad_budget_day) * 100),
        )
        params = {
            "name": f"shopai_{launch_id}",
            "objective": "OUTCOME_SALES",
            # PAUSED until owner approves (§4b.G). Activator
            # flips to ACTIVE via its own paranoid-mode path.
            "status": "PAUSED",
            "daily_budget": daily_budget_cents,
        }
        result = adapter.execute(
            Capability.ADS_CREATE_CAMPAIGN, params,
        )
        if not result.ok:
            # Return a structured failure (not raise StepSkip)
            # — StepSkip means "this step doesn't apply";
            # here the step DID apply and failed. Let the
            # runner mark it failed via the error string.
            raise RuntimeError(
                f"Meta Ads create_campaign failed: "
                f"{getattr(result, 'error', 'unknown')}",
            )
        data = dict(result.data or {})
        campaign_id = str(data.get("campaign_id") or "")
        # Populate context.ad_campaign so downstream monitor
        # + kill-switch steps have the id.
        context.ad_campaign = {
            "campaign_id": campaign_id,
            "name": params["name"],
            "status": params["status"],
            "daily_budget_usd": float(context.goal.ad_budget_day),
            "kill_rule": {
                "roas_below": context.goal.ad_kill_roas,
                "after_days": context.goal.ad_kill_after_days,
            },
            "live_gate": live,
        }
        return dict(context.ad_campaign)
