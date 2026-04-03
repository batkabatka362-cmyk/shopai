"""Intelligence Layer — flow orchestrator.

Pipeline (strictly sequential — each step builds on prior):
  simulation_lab → auto_research → learning_loop → global_brain → meta_governance

ALL engines are REQUIRED. Failure at any step halts the layer.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import INTELLIGENCE_LAYER_CONFIG

logger = logging.getLogger(__name__)


class IntelligenceLayerFlow:
    """Intelligence Layer — orchestrates intelligence engines sequentially."""

    LAYER_NAME = "intelligence_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full intelligence-layer pipeline.

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

        # ---- Run engines sequentially (all required) ----
        required = set(INTELLIGENCE_LAYER_CONFIG["required_engines"])
        engine_names = INTELLIGENCE_LAYER_CONFIG["engines"]
        accumulated_data: dict[str, Any] = payload.get("data", {}) or {}
        engine_results: dict[str, Any] = {}
        warnings: list[str] = []

        current_input = payload

        for name in engine_names:
            engine = get_engine(name)
            if engine is None:
                msg = f"Engine '{name}' not found in registry"
                if name in required:
                    return self._fail(msg, time.monotonic() - start)
                warnings.append(msg)
                logger.warning("%s: %s — skipping", self.LAYER_NAME, msg)
                continue

            try:
                result = engine.run(current_input)
            except Exception as exc:
                msg = f"Engine '{name}' raised: {exc}"
                if name in required:
                    return self._fail(msg, time.monotonic() - start)
                warnings.append(msg)
                logger.warning("%s: %s — continuing", self.LAYER_NAME, msg)
                continue

            if result.get("status") == "error":
                msg = f"Engine '{name}' failed: {result.get('error', 'unknown')}"
                if name in required:
                    return self._fail(msg, time.monotonic() - start)
                warnings.append(msg)
                logger.warning("%s: %s — continuing", self.LAYER_NAME, msg)
                continue

            # Accumulate successful data
            engine_data = result.get("data", {}) or {}
            accumulated_data.update(engine_data)
            engine_results[name] = result

            # Enrich input for the next engine
            current_input = {
                "status": "success",
                "data": accumulated_data,
                "meta": payload.get("meta", {}),
                "error": None,
            }

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(engine_names),
                "warnings": warnings,
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
                "layer": self.LAYER_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
