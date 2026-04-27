"""Gift Card Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Program Designer → Redemption Tracker →
  Breakage Estimator → Promotion Planner → Memory Writer → Output

Engine contract:
  Input:  {status, data: {gift_cards, redemptions, program_config}, meta, error}
  Output: {status, data: {program_health, breakage_estimate, active_cards, promotions}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .program_designer import design_program
from .redemption_tracker import track_redemptions
from .breakage_estimator import estimate_breakage
from .promotion_planner import plan_promotions
from .memory_reader import read_past_gift_card
from .memory_writer import write_gift_card_result
from engines._shopify_hydrator import hydrate


class GiftCardEngine:
    """Gift Card Engine — orchestrator only, no logic."""

    ENGINE_NAME = "gift_card"

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

        gift_cards = data.get("gift_cards", [])
        redemptions = data.get("redemptions", [])
        program_config = data.get("program_config", {})

        # Auto-hydrate gift_cards from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        gift_cards = hydrate(
            supplied=gift_cards if isinstance(gift_cards, list) else [],
            capability_name="SHOPIFY_LIST_GIFT_CARDS",
            list_field="gift_cards",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not gift_cards:
            return self._fail("Gift cards list is required", 0.0)

        _past = read_past_gift_card(limit=5)

        prog_result = design_program(gift_cards=gift_cards, program_config=program_config)
        if prog_result.get("status") == "error":
            return self._fail(f"Program design failed: {prog_result.get('error')}", time.monotonic() - start)
        program_health = prog_result.get("program_health", {})
        active_cards = prog_result.get("active_cards", [])

        redem_result = track_redemptions(redemptions=redemptions, gift_cards=gift_cards)
        if redem_result.get("status") == "error":
            return self._fail(f"Redemption tracking failed: {redem_result.get('error')}", time.monotonic() - start)
        program_health["redemption_stats"] = redem_result.get("redemption_stats", {})

        break_result = estimate_breakage(gift_cards=gift_cards, program_health=program_health)
        if break_result.get("status") == "error":
            return self._fail(f"Breakage estimation failed: {break_result.get('error')}", time.monotonic() - start)
        breakage_estimate = break_result.get("breakage", {})

        promo_result = plan_promotions(program_health=program_health, program_config=program_config)
        if promo_result.get("status") == "error":
            return self._fail(f"Promotion planning failed: {promo_result.get('error')}", time.monotonic() - start)
        promotions = promo_result.get("promotions", [])

        _write = write_gift_card_result(program_health=program_health, breakage=breakage_estimate)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "program_health": program_health,
                "breakage_estimate": breakage_estimate,
                "active_cards": active_cards,
                "promotions": promotions,
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
