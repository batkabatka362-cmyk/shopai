"""Product Layer — flow orchestrator.

Pipeline:
  product_selection → product_filter → product_scoring → product_validation →
  product_ranking → product_risk + product_lifecycle (parallel) → catalog

- Linear pipeline that narrows product candidates at each step.
- product_risk and product_lifecycle are independent and can run in parallel.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import PRODUCT_LAYER_CONFIG

logger = logging.getLogger(__name__)


class ProductLayerFlow:
    """Product Layer — orchestrates product-pipeline engines."""

    LAYER_NAME = "product_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full product-layer pipeline.

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
        required = set(PRODUCT_LAYER_CONFIG["required_engines"])
        accumulated_data: dict[str, Any] = payload.get("data", {}) or {}
        engine_results: dict[str, Any] = {}
        warnings: list[str] = []

        # -- Phase 1: Linear pipeline up to product_ranking --
        linear_phase = [
            "product_selection",
            "product_filter",
            "product_scoring",
            "product_validation",
            "product_ranking",
        ]
        for name in linear_phase:
            enriched_input = {
                "status": "success",
                "data": accumulated_data,
                "meta": payload.get("meta", {}),
                "error": None,
            }
            result = self._run_engine(name, enriched_input, required, warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                engine_data = result.get("data", {}) or {}
                accumulated_data.update(engine_data)
                engine_results[name] = result

        # -- Phase 2: Parallel group — product_risk + product_lifecycle --
        # NOTE: These two engines are independent and could run concurrently.
        for name in ("product_risk", "product_lifecycle"):
            enriched_input = {
                "status": "success",
                "data": accumulated_data,
                "meta": payload.get("meta", {}),
                "error": None,
            }
            result = self._run_engine(name, enriched_input, required, warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                engine_data = result.get("data", {}) or {}
                accumulated_data.update(engine_data)
                engine_results[name] = result

        # -- Phase 3: catalog --
        enriched_input = {
            "status": "success",
            "data": accumulated_data,
            "meta": payload.get("meta", {}),
            "error": None,
        }
        result = self._run_engine("catalog", enriched_input, required, warnings)
        if result is None and "catalog" in required:
            return self._fail(
                "Required engine 'catalog' failed",
                time.monotonic() - start,
            )
        if result is not None:
            engine_data = result.get("data", {}) or {}
            accumulated_data.update(engine_data)
            engine_results["catalog"] = result

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(PRODUCT_LAYER_CONFIG["engines"]),
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
