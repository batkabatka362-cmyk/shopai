"""Loyalty Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Customer Data → Program Designer → Points Calculator → Tier Manager →
  Reward Recommender → Memory Writer → Output

PURPOSE: Manage loyalty/rewards program.

Engine contract:
  Input:  {status, data: {customers, orders, program_config, current_points}, meta, error}
  Output: {status, data: {program: {tiers, point_rules}, customer_status, reward_recommendations, program_health}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .program_designer import design_program
from .points_calculator import calculate_points
from .tier_manager import manage_tiers
from .reward_recommender import recommend_rewards
from .memory_reader import read_past_loyalty
from .memory_writer import write_loyalty_result


class LoyaltyEngine:
    """Loyalty Engine — orchestrator only, no logic."""

    ENGINE_NAME = "loyalty"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full loyalty pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            LoyaltyOutput dict.
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

        customers = data.get("customers", [])
        orders = data.get("orders", [])
        program_config = data.get("program_config", {})
        current_points = data.get("current_points", {})

        if not customers:
            return self._fail("Customer list is required", 0.0)

        # ---- Stage 1: Read past loyalty data (non-blocking) ----
        _past = read_past_loyalty(limit=5)

        # ---- Stage 2: Program Designer ----
        design_result = design_program(
            program_config=program_config,
            customers=customers,
        )
        if design_result.get("status") == "error":
            return self._fail(
                f"Program design failed: {design_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        design = design_result.get("design", {})
        tiers = design.get("tiers", [])
        point_rules = design.get("point_rules", [])
        earning_rate = float(design.get("earning_rate", 10.0))

        # ---- Stage 3: Points Calculator ----
        points_result = calculate_points(
            customers=customers,
            orders=orders,
            earning_rate=earning_rate,
            current_points=current_points,
        )
        if points_result.get("status") == "error":
            return self._fail(
                f"Points calculation failed: {points_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        points_calculations = points_result.get("calculations", [])

        # ---- Stage 4: Tier Manager ----
        tier_result = manage_tiers(
            points_calculations=points_calculations,
            tiers=tiers,
        )
        if tier_result.get("status") == "error":
            return self._fail(
                f"Tier management failed: {tier_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tier_statuses = tier_result.get("statuses", [])
        tier_distribution = tier_result.get("tier_distribution", {})

        # ---- Stage 5: Reward Recommender ----
        reward_catalog = program_config.get("reward_catalog", [])
        reward_result = recommend_rewards(
            tier_statuses=tier_statuses,
            reward_catalog=reward_catalog,
        )
        if reward_result.get("status") == "error":
            return self._fail(
                f"Reward recommendation failed: {reward_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        reward_recommendations = reward_result.get("recommendations", [])

        # ---- Stage 6: Build program health ----
        total_points = sum(int(c.get("points_balance", 0)) for c in points_calculations)
        active_count = sum(1 for c in points_calculations if int(c.get("points_balance", 0)) > 0)
        total_members = len(customers)

        program_health: dict[str, Any] = {
            "total_members": total_members,
            "active_members": active_count,
            "total_points_outstanding": total_points,
            "avg_points_per_member": round(total_points / total_members, 1) if total_members > 0 else 0.0,
            "tier_distribution": tier_distribution,
        }

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_loyalty_result(
            customer_status=tier_statuses,
            program_health=program_health,
            reward_recommendations=reward_recommendations,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "program": {
                    "tiers": tiers,
                    "point_rules": point_rules,
                },
                "customer_status": tier_statuses,
                "reward_recommendations": reward_recommendations,
                "program_health": program_health,
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
