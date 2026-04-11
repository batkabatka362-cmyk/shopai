"""Operations Layer — flow orchestrator.

Pipeline:
  inventory → stock_prediction + supplier (parallel)
  → supplier_discovery (if supplier failed or flagged)
  → shipping_optimization → returns_management

- inventory and shipping_optimization are REQUIRED.
- stock_prediction, supplier, supplier_discovery, returns_management are optional.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import OPERATIONS_LAYER_CONFIG

logger = logging.getLogger(__name__)


class OperationsLayerFlow:
    """Operations Layer — orchestrates supply-chain engines."""

    LAYER_NAME = "operations_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full operations-layer pipeline.

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

        # ---- Setup ----
        required = set(OPERATIONS_LAYER_CONFIG["required_engines"])
        accumulated_data: dict[str, Any] = payload.get("data", {}) or {}
        engine_results: dict[str, Any] = {}
        warnings: list[str] = []

        def _make_input() -> dict[str, Any]:
            return {
                "status": "success",
                "data": accumulated_data,
                "meta": payload.get("meta", {}),
                "error": None,
            }

        def _run_engine(name: str) -> bool:
            """Run a single engine. Returns True on success (or optional skip)."""
            engine = get_engine(name)
            if engine is None:
                msg = f"Engine '{name}' not found in registry"
                if name in required:
                    return False
                warnings.append(msg)
                logger.warning("%s: %s — skipping", self.LAYER_NAME, msg)
                return True

            try:
                result = engine.run(_make_input())
            except Exception as exc:
                msg = f"Engine '{name}' raised: {exc}"
                if name in required:
                    return False
                warnings.append(msg)
                logger.warning("%s: %s — continuing", self.LAYER_NAME, msg)
                return True

            if result.get("status") == "error":
                msg = f"Engine '{name}' failed: {result.get('error', 'unknown')}"
                if name in required:
                    return False
                warnings.append(msg)
                logger.warning("%s: %s — continuing", self.LAYER_NAME, msg)
                return True

            engine_data = result.get("data", {}) or {}
            accumulated_data.update(engine_data)
            engine_results[name] = result
            return True

        # ---- Stage 1: inventory (required) ----
        if not _run_engine("inventory"):
            return self._fail(
                "Required engine 'inventory' failed",
                time.monotonic() - start,
            )

        # ---- Stage 2: stock_prediction + supplier (parallel) ----
        supplier_ok = True
        for name in ("stock_prediction", "supplier"):
            if not _run_engine(name):
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if name == "supplier" and name not in engine_results:
                supplier_ok = False

        # ---- Stage 3: supplier_discovery (if supplier failed/missing) ----
        if not supplier_ok:
            logger.info(
                "%s: supplier engine did not succeed — running supplier_discovery",
                self.LAYER_NAME,
            )
            _run_engine("supplier_discovery")

        # ---- Stage 4: shipping_optimization (required) ----
        if not _run_engine("shipping_optimization"):
            return self._fail(
                "Required engine 'shipping_optimization' failed",
                time.monotonic() - start,
            )

        # ---- Stage 5: returns_management (optional) ----
        _run_engine("returns_management")

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(OPERATIONS_LAYER_CONFIG["engines"]),
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
