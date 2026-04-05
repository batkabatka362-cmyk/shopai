"""Analysis Layer — flow orchestrator.

Pipeline:
  market_research + competition_analyzer (parallel) → trend_detection →
  demand_analysis → forecasting → opportunity_detection → opportunity_scoring

- market_research and competition_analyzer are independent and can run in parallel.
- trend_detection depends on both outputs.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import ANALYSIS_LAYER_CONFIG

logger = logging.getLogger(__name__)


class AnalysisLayerFlow:
    """Analysis Layer — orchestrates market/competition analysis engines."""

    LAYER_NAME = "analysis_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full analysis-layer pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            Unified layer output dict.
        """
        start = time.monotonic()

        # ---- Validate input ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "error":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        # ---- Run engines ----
        required = set(ANALYSIS_LAYER_CONFIG["required_engines"])
        accumulated_data: dict[str, Any] = payload.get("data", {}) or {}
        engine_results: dict[str, Any] = {}
        warnings: list[str] = []

        # -- Parallel group 1: market_research + competition_analyzer --
        # NOTE: These two engines are independent and could run concurrently.
        # Running sequentially here; a true async executor can parallelize them.
        for name in ("market_research", "competition_analyzer"):
            result = self._run_engine(
                name, payload, required, warnings,
                time.monotonic() - start,
            )
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed (see warnings)",
                    time.monotonic() - start,
                )
            if result is not None:
                engine_data = result.get("data", {}) or {}
                accumulated_data.update(engine_data)
                engine_results[name] = result

        # -- Sequential: trend_detection → demand_analysis → forecasting →
        #    opportunity_detection → opportunity_scoring --
        sequential = [
            "trend_detection",
            "demand_analysis",
            "forecasting",
            "opportunity_detection",
            "opportunity_scoring",
        ]
        for name in sequential:
            enriched_input = {
                "status": "success",
                "data": accumulated_data,
                "meta": payload.get("meta", {}),
                "error": None,
            }
            result = self._run_engine(
                name, enriched_input, required, warnings,
                time.monotonic() - start,
            )
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed (see warnings)",
                    time.monotonic() - start,
                )
            if result is not None:
                engine_data = result.get("data", {}) or {}
                # Don't let empty results overwrite non-empty accumulated data
                for k, v in engine_data.items():
                    if v or k not in accumulated_data or not accumulated_data[k]:
                        accumulated_data[k] = v
                engine_results[name] = result

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(ANALYSIS_LAYER_CONFIG["engines"]),
                "warnings": warnings,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _run_engine(
        self,
        name: str,
        input_payload: dict[str, Any],
        required: set[str],
        warnings: list[str],
        elapsed_so_far: float,
    ) -> dict[str, Any] | None:
        """Run a single engine, returning its result or None on failure."""
        engine = get_engine(name)
        if engine is None:
            msg = f"Engine '{name}' not found in registry"
            warnings.append(msg)
            logger.warning("%s: %s", self.LAYER_NAME, msg)
            return None

        try:
            result = engine.run(input_payload)
        except Exception as exc:
            msg = f"Engine '{name}' raised: {exc}"
            warnings.append(msg)
            logger.warning("%s: %s", self.LAYER_NAME, msg)
            return None

        if result.get("status") == "error":
            msg = f"Engine '{name}' failed: {result.get('error', 'unknown')}"
            warnings.append(msg)
            logger.warning("%s: %s", self.LAYER_NAME, msg)
            return None

        return result

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "layer": self.LAYER_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
