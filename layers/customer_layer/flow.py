"""Customer Layer — flow orchestrator.

Pipeline:
  customer_segmentation → churn_prediction + sentiment_analysis (parallel) →
  review_management → customer_support + chatbot (parallel) → audience_targeting

- customer_segmentation and audience_targeting are required.
- Two parallel groups noted in comments.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import CUSTOMER_LAYER_CONFIG

logger = logging.getLogger(__name__)


class CustomerLayerFlow:
    """Customer Layer — orchestrates customer-intelligence engines."""

    LAYER_NAME = "customer_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full customer-layer pipeline.

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
        required = set(CUSTOMER_LAYER_CONFIG["required_engines"])
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

        # -- Step 1: customer_segmentation --
        result = self._run_engine("customer_segmentation", _make_input(), warnings)
        if result is None and "customer_segmentation" in required:
            return self._fail(
                "Required engine 'customer_segmentation' failed",
                time.monotonic() - start,
            )
        if result is not None:
            accumulated_data.update(result.get("data", {}) or {})
            engine_results["customer_segmentation"] = result

        # -- Step 2: churn_prediction + sentiment_analysis (parallel) --
        # NOTE: These two engines are independent and could run concurrently.
        for name in ("churn_prediction", "sentiment_analysis"):
            result = self._run_engine(name, _make_input(), warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                accumulated_data.update(result.get("data", {}) or {})
                engine_results[name] = result

        # -- Step 3: review_management --
        result = self._run_engine("review_management", _make_input(), warnings)
        if result is None and "review_management" in required:
            return self._fail(
                "Required engine 'review_management' failed",
                time.monotonic() - start,
            )
        if result is not None:
            accumulated_data.update(result.get("data", {}) or {})
            engine_results["review_management"] = result

        # -- Step 4: customer_support + chatbot (parallel) --
        # NOTE: These two engines are independent and could run concurrently.
        for name in ("customer_support", "chatbot"):
            result = self._run_engine(name, _make_input(), warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                accumulated_data.update(result.get("data", {}) or {})
                engine_results[name] = result

        # -- Step 5: audience_targeting --
        result = self._run_engine("audience_targeting", _make_input(), warnings)
        if result is None and "audience_targeting" in required:
            return self._fail(
                "Required engine 'audience_targeting' failed",
                time.monotonic() - start,
            )
        if result is not None:
            accumulated_data.update(result.get("data", {}) or {})
            engine_results["audience_targeting"] = result

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(CUSTOMER_LAYER_CONFIG["engines"]),
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
