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

        # TODO(brain): replace stub with the real adapter call:
        # from core.adapters.ads.meta_ads import MetaAdsAdapter
        # adapter = MetaAdsAdapter()
        # campaign = adapter.create_campaign(
        #     name=f"shopai_{context.launch_id}",
        #     daily_budget=context.goal.ad_budget_day,
        #     product_url=context.shopify_product["storefront_url"],
        #     pixel_id=os.environ["META_ADS_PIXEL_ID"],
        #     creatives=context.creative["variants"],
        #     kill_rule={"roas_below": context.goal.ad_kill_roas,
        #                "after_days": context.goal.ad_kill_after_days},
        # )
        raise StepSkip(
            "Meta Ads create_campaign not implemented "
            "(MetaAdsAdapter exists as adapter — needs ads_launch wire-up)"
        )
