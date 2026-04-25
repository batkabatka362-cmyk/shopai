"""Step 9 — Hand off to the autonomous monitor.

Records the launch into ``core/memory/`` so the daemon's per-cycle
``revenue_strategy`` / ``roas_kill_switch`` phases pick it up. Without
this step the launch is invisible to the brain and no learning happens.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext
from ._base import Step


logger = get_logger("workflows.launch.monitor")


class MonitorStep(Step):
    name = "monitor"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        record = {
            "launch_id": context.launch_id,
            "shopify_product_id": context.shopify_product.get("product_id"),
            "shopify_handle": context.shopify_product.get("handle"),
            "ad_campaign_id": context.ad_campaign.get("campaign_id"),
            "kill_rule": context.tracking.get("kill_rule", {}),
            "registered_at": time.time(),
            "kpis_to_watch": ["roas", "cvr", "cpa", "aov"],
        }

        try:
            from core.memory.intelligence import get_memory_intelligence
            tags = ["launch", "monitor"]
            if context.goal.niche:
                tags.append(context.goal.niche)
            get_memory_intelligence().create(
                category="launch",
                content=record,
                action="launch_registered",
                score=3.0,
                tags=tags,
            )
        except Exception as exc:
            logger.warning("memory create failed for launch %s: %s",
                           context.launch_id, exc)

        logger.info("Launch monitored: %s", record)
        return record
