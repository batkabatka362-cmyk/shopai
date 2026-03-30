"""Ad Flow

Chains: ads → creative_generation → traffic → conversion

Input:  Ad brief and target audience
Output: Complete ad package with creative and traffic plan
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.ad")


class AdFlow:
    """End-to-end ad creation and deployment workflow."""

    def __init__(self) -> None:
        self._ads = get_engine("ads")
        self._creative = get_engine("creative_generation")
        self._traffic = get_engine("traffic")
        self._conversion = get_engine("conversion")

    def run(self, ad_brief: dict[str, Any], target_audience: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting ad flow", flow_id)
        results: dict[str, Any] = {}

        # Step 1: Create ads
        ads_out = self._ads.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="ads",
            data={"ad_brief": ad_brief, "target_audience": target_audience},
        ))
        results["ads"] = ads_out.to_dict()

        # Step 2: Generate creatives
        creative_out = self._creative.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="creative_generation",
            data={"brief": ads_out.result, "brand_guidelines": ad_brief.get("brand", {})},
        ))
        results["creative"] = creative_out.to_dict()

        # Step 3: Traffic plan
        traffic_out = self._traffic.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="traffic",
            data={"traffic_data": ads_out.result, "allocation_goals": target_audience},
        ))
        results["traffic"] = traffic_out.to_dict()

        # Step 4: Conversion setup
        conv_out = self._conversion.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="conversion",
            data={"conversion_data": traffic_out.result, "touchpoints": ads_out.result},
        ))
        results["conversion"] = conv_out.to_dict()

        return {
            "flow_id": flow_id,
            "flow": "ad",
            "status": "completed",
            "result": results,
        }
