"""Influencer Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Influencer Finder → Scoring Engine →
  Campaign Planner → Outreach Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {category, target_audience, budget, campaign_type}, meta, error}
  Output: {status, data: {influencers, campaign_plan, estimated_roi, outreach_templates}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .influencer_finder import find_influencers
from .scoring_engine import score_influencers
from .campaign_planner import plan_campaign
from .outreach_builder import build_outreach
from .memory_reader import read_past_campaigns
from .memory_writer import write_campaign_result


class InfluencerEngine:
    """Influencer Engine — orchestrator only, no logic."""

    ENGINE_NAME = "influencer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full influencer pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            InfluencerOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        category = str(data.get("category", ""))
        target_audience = data.get("target_audience", {})
        budget = float(data.get("budget", 0.0))
        campaign_type = str(data.get("campaign_type", "sponsored_post"))

        if not category:
            return self._fail("Category is required", 0.0)
        if budget <= 0:
            return self._fail("Budget must be positive", 0.0)

        # ---- Stage 1: Read past campaigns (non-blocking) ----
        _past = read_past_campaigns(limit=5)

        # ---- Stage 2: Influencer Finder ----
        finder_result = find_influencers(
            category=category,
            target_audience=target_audience,
            budget=budget,
        )
        if finder_result.get("status") == "error":
            return self._fail(
                f"Influencer finding failed: {finder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        candidates = finder_result.get("candidates", [])

        if not candidates:
            return self._fail("No influencer candidates found", time.monotonic() - start)

        # ---- Stage 3: Scoring Engine ----
        scoring_result = score_influencers(
            candidates=candidates,
            target_audience=target_audience,
            budget=budget,
        )
        if scoring_result.get("status") == "error":
            return self._fail(
                f"Influencer scoring failed: {scoring_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scored = scoring_result.get("scored", [])

        # ---- Stage 4: Campaign Planner ----
        planner_result = plan_campaign(
            scored_influencers=scored,
            budget=budget,
            campaign_type=campaign_type,
            category=category,
        )
        if planner_result.get("status") == "error":
            return self._fail(
                f"Campaign planning failed: {planner_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        campaign_plan = planner_result.get("campaign_plan", {})
        estimated_roi = float(planner_result.get("estimated_roi", 0.0))

        # ---- Stage 5: Outreach Builder ----
        outreach_result = build_outreach(
            scored_influencers=scored,
            campaign_plan=campaign_plan,
            category=category,
        )
        if outreach_result.get("status") == "error":
            return self._fail(
                f"Outreach building failed: {outreach_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        outreach_templates = outreach_result.get("templates", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_campaign_result(
            influencers=scored,
            campaign_plan=campaign_plan,
            estimated_roi=estimated_roi,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "influencers": scored,
                "campaign_plan": campaign_plan,
                "estimated_roi": estimated_roi,
                "outreach_templates": outreach_templates,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
