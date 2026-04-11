"""Campaign Strategy Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Channel Planner → Phase Builder →
  Budget Allocator → Timeline Creator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {goal, budget, audience, products, channels, duration_days}, meta, error}
  Output: {status, data: {strategy, budget_allocation, expected_results, milestones}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .channel_planner import plan_channels
from .phase_builder import build_phases
from .budget_allocator import allocate_budget
from .timeline_creator import create_timeline
from .memory_reader import read_past_campaigns
from .memory_writer import write_campaign_result


class CampaignStrategyEngine:
    """Campaign Strategy Engine — orchestrator only, no logic."""

    ENGINE_NAME = "campaign_strategy"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        goal = str(data.get("goal", ""))
        budget = float(data.get("budget", 0.0))
        audience = data.get("audience", {})
        products = data.get("products", [])
        channels = data.get("channels", [])
        duration_days = int(data.get("duration_days", 30))

        if not goal:
            return self._fail("Campaign goal is required", 0.0)
        if budget <= 0:
            return self._fail("Budget must be positive", 0.0)
        if not channels:
            return self._fail("At least one channel is required", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_campaigns(limit=5)

        # ---- Stage 2: Channel Planner ----
        channel_result = plan_channels(channels=channels, budget=budget, audience=audience)
        if channel_result.get("status") == "error":
            return self._fail(f"Channel planning failed: {channel_result.get('error', 'unknown')}", time.monotonic() - start)
        channel_plans = channel_result.get("channel_plans", [])

        # ---- Stage 3: Phase Builder ----
        phase_result = build_phases(duration_days=duration_days, channels=channels, goal=goal)
        if phase_result.get("status") == "error":
            return self._fail(f"Phase building failed: {phase_result.get('error', 'unknown')}", time.monotonic() - start)
        phases = phase_result.get("phases", [])

        # ---- Stage 4: Budget Allocator ----
        budget_result = allocate_budget(budget=budget, channel_plans=channel_plans, phases=phases)
        if budget_result.get("status") == "error":
            return self._fail(f"Budget allocation failed: {budget_result.get('error', 'unknown')}", time.monotonic() - start)
        allocations = budget_result.get("allocations", [])

        # ---- Stage 5: Timeline Creator ----
        timeline_result = create_timeline(phases=phases, duration_days=duration_days)
        if timeline_result.get("status") == "error":
            return self._fail(f"Timeline creation failed: {timeline_result.get('error', 'unknown')}", time.monotonic() - start)
        milestones = timeline_result.get("milestones", [])
        expected_results = timeline_result.get("expected_results", {})

        # ---- Stage 6: Build strategy output ----
        strategy = {
            "phases": phases,
            "channels": channel_plans,
            "timeline": milestones,
        }

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write = write_campaign_result(strategy=strategy, budget_allocation=allocations, expected_results=expected_results)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "strategy": strategy,
                "budget_allocation": allocations,
                "expected_results": expected_results,
                "milestones": milestones,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
