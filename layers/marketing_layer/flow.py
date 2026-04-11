"""Marketing Layer — flow orchestrator.

Pipeline:
  content_generation → email_marketing + social_media + landing_page (parallel) →
  influencer + affiliate + video_marketing (parallel) → ab_testing

- content_generation and ab_testing are required.
- Two parallel groups of distribution/promotion engines in between.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.registry import get_engine

from .config import MARKETING_LAYER_CONFIG

logger = logging.getLogger(__name__)


class MarketingLayerFlow:
    """Marketing Layer — orchestrates marketing-pipeline engines."""

    LAYER_NAME = "marketing_layer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full marketing-layer pipeline.

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
        required = set(MARKETING_LAYER_CONFIG["required_engines"])
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

        # -- Step 1: content_generation --
        result = self._run_engine("content_generation", _make_input(), warnings)
        if result is None and "content_generation" in required:
            return self._fail(
                "Required engine 'content_generation' failed",
                time.monotonic() - start,
            )
        if result is not None:
            accumulated_data.update(result.get("data", {}) or {})
            engine_results["content_generation"] = result

        # -- Step 2: email_marketing + social_media + landing_page (parallel) --
        # NOTE: These three engines are independent and could run concurrently.
        for name in ("email_marketing", "social_media", "landing_page"):
            result = self._run_engine(name, _make_input(), warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                accumulated_data.update(result.get("data", {}) or {})
                engine_results[name] = result

        # -- Step 3: influencer + affiliate + video_marketing (parallel) --
        # NOTE: These three engines are independent and could run concurrently.
        for name in ("influencer", "affiliate", "video_marketing"):
            result = self._run_engine(name, _make_input(), warnings)
            if result is None and name in required:
                return self._fail(
                    f"Required engine '{name}' failed",
                    time.monotonic() - start,
                )
            if result is not None:
                accumulated_data.update(result.get("data", {}) or {})
                engine_results[name] = result

        # -- Step 4: ab_testing --
        result = self._run_engine("ab_testing", _make_input(), warnings)
        if result is None and "ab_testing" in required:
            return self._fail(
                "Required engine 'ab_testing' failed",
                time.monotonic() - start,
            )
        if result is not None:
            accumulated_data.update(result.get("data", {}) or {})
            engine_results["ab_testing"] = result

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": accumulated_data,
            "meta": {
                "layer": self.LAYER_NAME,
                "engines_ran": list(engine_results.keys()),
                "engines_total": len(MARKETING_LAYER_CONFIG["engines"]),
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
