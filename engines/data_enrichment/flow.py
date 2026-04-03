"""Data Enrichment Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Stat Calculator → Feature Builder →
  Quality Scorer → Gap Detector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {raw_data, enrichment_level}, meta, error}
  Output: {status, data: {enriched_data, features, quality_score, gaps}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .stat_calculator import calculate_stats
from .feature_builder import build_features
from .quality_scorer import score_quality
from .gap_detector import detect_gaps
from .memory_reader import read_past_enrichments
from .memory_writer import write_enrichment_result


class DataEnrichmentEngine:
    """Data Enrichment Engine — orchestrator only, no logic."""

    ENGINE_NAME = "data_enrichment"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full data enrichment pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DataEnrichmentOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        raw_data = data.get("raw_data", [])
        enrichment_level = str(data.get("enrichment_level", "standard"))

        if not raw_data:
            return self._fail("raw_data is required", 0.0)

        # ---- Stage 1: Read past enrichments (non-blocking) ----
        _past = read_past_enrichments(limit=5)

        # ---- Stage 2: Stat Calculator ----
        stat_result = calculate_stats(
            raw_data=raw_data,
            enrichment_level=enrichment_level,
        )
        if stat_result.get("status") == "error":
            return self._fail(
                f"Stat calculation failed: {stat_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        computed_stats = stat_result.get("stats", [])

        # ---- Stage 3: Feature Builder ----
        feature_result = build_features(
            raw_data=raw_data,
            computed_stats=computed_stats,
            enrichment_level=enrichment_level,
        )
        if feature_result.get("status") == "error":
            return self._fail(
                f"Feature building failed: {feature_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        features = feature_result.get("features", [])

        # ---- Stage 4: Build enriched data ----
        stats_map = {
            s.get("record_id", ""): s.get("stats", {})
            for s in computed_stats
        }
        enriched_data: list[dict[str, Any]] = []
        for record in raw_data:
            enriched = dict(record)
            record_id = str(record.get("id", record.get("product_id", "unknown")))
            enriched["_computed_stats"] = stats_map.get(record_id, {})
            enriched_data.append(enriched)

        # ---- Stage 5: Quality Scorer ----
        quality_result = score_quality(
            raw_data=raw_data,
            enriched_data=enriched_data,
        )
        if quality_result.get("status") == "error":
            return self._fail(
                f"Quality scoring failed: {quality_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        quality_score = quality_result.get("overall_quality_score", 0.0)

        # ---- Stage 6: Gap Detector ----
        gap_result = detect_gaps(
            raw_data=raw_data,
        )
        if gap_result.get("status") == "error":
            return self._fail(
                f"Gap detection failed: {gap_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        gaps = gap_result.get("gaps", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_enrichment_result(
            enriched_data=enriched_data,
            features=features,
            quality_score=quality_score,
            gaps=gaps,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "enriched_data": enriched_data,
                "features": features,
                "quality_score": quality_score,
                "gaps": gaps,
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
