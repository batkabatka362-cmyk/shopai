"""Financial Layer — flow orchestrator.

Pipeline:
  financial → kpi_tracking + monetization (parallel)
  → profit_optimization → payment_optimization

- financial and profit_optimization are REQUIRED.
- kpi_tracking, monetization, payment_optimization are optional.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import FINANCIAL_LAYER_CONFIG

logger = logging.getLogger(__name__)


class FinancialLayerFlow:
    """Financial Layer — orchestrates finance engines."""

    LAYER_NAME = "financial_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full financial-layer pipeline.

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
        required = set(FINANCIAL_LAYER_CONFIG["required_engines"])
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

        # ---- Stage 1: financial (required) ----
        if not _run_engine("financial"):
            return self._fail(
                "Required engine 'financial' failed",
                time.monotonic() - start,
            )

        # ---- Stage 2: kpi_tracking + monetization (parallel) ----
        for name in ("kpi_tracking", "monetization"):
            if not _run_engine(name):
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )

        # ---- Stage 3: profit_optimization (required) ----
        if not _run_engine("profit_optimization"):
            return self._fail(
                "Required engine 'profit_optimization' failed",
                time.monotonic() - start,
            )

        # ---- Stage 4: payment_optimization (optional) ----
        _run_engine("payment_optimization")

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(FINANCIAL_LAYER_CONFIG["engines"]),
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
