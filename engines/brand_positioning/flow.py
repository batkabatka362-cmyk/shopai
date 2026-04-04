"""Brand Positioning Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Brand + Competitors → Position Mapper → Gap Analyzer →
  Differentiation Scorer → Strategy Advisor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {brand: {name, values, price_range, quality}, competitors: [{name, price_range, quality, positioning}]}, meta, error}
  Output: {status, data: {position_map, gaps, differentiation_scores, strategy_recommendations, competitive_advantages}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .position_mapper import map_positions
from .gap_analyzer import analyze_gaps
from .differentiation_scorer import score_differentiation
from .strategy_advisor import advise_strategy
from .memory_reader import read_past_positionings
from .memory_writer import write_positioning_result


class BrandPositioningEngine:
    """Brand Positioning Engine — orchestrator only, no logic."""

    ENGINE_NAME = "brand_positioning"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full brand positioning pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BrandPositioningOutput dict.
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

        brand = data.get("brand", {})
        if not isinstance(brand, dict) or not brand.get("name"):
            return self._fail("Brand info with 'name' is required", 0.0)

        competitors = data.get("competitors", [])

        # ---- Stage 1: Read past positionings (non-blocking) ----
        _past = read_past_positionings(limit=5)

        # ---- Stage 2: Position Mapper ----
        position_result = map_positions(
            brand=brand,
            competitors=competitors,
        )
        if position_result.get("status") == "error":
            return self._fail(
                f"Position mapping failed: {position_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        position_map = position_result.get("position_map", {})

        # ---- Stage 3: Gap Analyzer ----
        gap_result = analyze_gaps(
            position_map=position_map,
        )
        if gap_result.get("status") == "error":
            return self._fail(
                f"Gap analysis failed: {gap_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        gaps = gap_result.get("gaps", [])

        # ---- Stage 4: Differentiation Scorer ----
        diff_result = score_differentiation(
            position_map=position_map,
            brand=brand,
            competitors=competitors,
        )
        if diff_result.get("status") == "error":
            return self._fail(
                f"Differentiation scoring failed: {diff_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        differentiation_scores = diff_result.get("differentiation_scores", [])

        # ---- Stage 5: Strategy Advisor ----
        strategy_result = advise_strategy(
            position_map=position_map,
            gaps=gaps,
            differentiation_scores=differentiation_scores,
            brand=brand,
        )
        if strategy_result.get("status") == "error":
            return self._fail(
                f"Strategy advising failed: {strategy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        strategy = strategy_result.get("strategy", {})
        strategy_recommendations = strategy.get("recommendations", [])
        competitive_advantages = strategy.get("competitive_advantages", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_positioning_result(
            position_map=position_map,
            gaps=gaps,
            differentiation_scores=differentiation_scores,
            strategy_recommendations=strategy_recommendations,
            competitive_advantages=competitive_advantages,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "position_map": position_map,
                "gaps": gaps,
                "differentiation_scores": differentiation_scores,
                "strategy_recommendations": strategy_recommendations,
                "competitive_advantages": competitive_advantages,
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
