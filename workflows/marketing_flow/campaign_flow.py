"""Campaign Flow

Chains: market_research → marketing → campaign → content_generation

Input:  Market data and budget
Output: Complete campaign plan with content
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput, EngineStatus
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.campaign")


class CampaignFlow:
    """End-to-end campaign creation workflow."""

    def __init__(self) -> None:
        self._research = get_engine("market_research")
        self._marketing = get_engine("marketing")
        self._campaign = get_engine("campaign")
        self._content = get_engine("content_generation")

    def run(self, market_data: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting campaign flow", flow_id)
        results: dict[str, Any] = {}

        # Step 1: Market research
        research_out = self._research.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="market_research",
            data={"market_data": market_data, "target_segment": budget.get("target", {})},
        ))
        results["research"] = research_out.to_dict()

        # Step 2: Marketing strategy
        marketing_out = self._marketing.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="marketing",
            data={"market_data": research_out.result, "budget": budget},
        ))
        results["marketing"] = marketing_out.to_dict()

        # Step 3: Campaign creation
        campaign_out = self._campaign.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="campaign",
            data={"campaign_brief": marketing_out.result, "target_audience": budget.get("target", {})},
        ))
        results["campaign"] = campaign_out.to_dict()

        # Step 4: Content generation
        content_out = self._content.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="content_generation",
            data={"product_data": campaign_out.result, "content_type": "campaign"},
        ))
        results["content"] = content_out.to_dict()

        return {
            "flow_id": flow_id,
            "flow": "campaign",
            "status": "completed",
            "result": results,
        }
