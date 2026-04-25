"""Step 8 — Tracking + ROAS kill rule wiring.

Two things wired here:
  1. Meta pixel + Shopify Customer Events — already auto-fires once the
     pixel id is set on the storefront, no per-launch work needed.
  2. ROAS kill rule — register a record in ``core/memory/`` so the
     daemon's autonomous-cycle ROAS phase will kill the campaign
     automatically when the threshold is breached.
"""
from __future__ import annotations

import time
from typing import Any

from ..context import LaunchContext
from ._base import Step


class TrackingStep(Step):
    name = "tracking"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        return {
            "kill_rule": {
                "campaign_id": context.ad_campaign.get("campaign_id"),
                "kill_roas": context.goal.ad_kill_roas,
                "after_days": context.goal.ad_kill_after_days,
                "scale_roas": 2.0,
                "scale_factor": 2.0,
                "registered_at": time.time(),
            },
            "pixel_id": context.ad_campaign.get("pixel_id"),
            "outcome_event_topic": f"launch.{context.launch_id}.outcome",
        }
