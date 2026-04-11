"""Data Collection Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Source Resolver → Data Fetcher →
  Data Normalizer → Freshness Checker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {sources, date_range, filters}, meta, error}
  Output: {status, data: {collected, total_records, freshness}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .source_resolver import resolve_sources
from .data_fetcher import fetch_data
from .data_normalizer import normalize_data
from .freshness_checker import check_freshness
from .memory_reader import read_past_collections
from .memory_writer import write_collection_result


class DataCollectionEngine:
    """Data Collection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "data_collection"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full data collection pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DataCollectionOutput dict.
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

        sources = data.get("sources", [])
        date_range = data.get("date_range", {})
        filters = data.get("filters", {})

        if not sources:
            return self._fail("Sources list is required", 0.0)

        # ---- Stage 1: Read past collections (non-blocking) ----
        _past = read_past_collections(limit=5)

        # ---- Stage 2: Source Resolver ----
        resolve_result = resolve_sources(
            requested_sources=sources,
            filters=filters,
        )
        if resolve_result.get("status") == "error":
            return self._fail(
                f"Source resolution failed: {resolve_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        resolved = resolve_result.get("resolved", [])

        if not resolved:
            return self._fail(
                f"No sources resolved. Unresolved: {resolve_result.get('unresolved', [])}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Data Fetcher ----
        fetch_result = fetch_data(
            resolved_sources=resolved,
            date_range=date_range,
            filters=filters,
        )
        if fetch_result.get("status") == "error":
            return self._fail(
                f"Data fetch failed: {fetch_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        fetched = fetch_result.get("fetched", [])

        # ---- Stage 4: Data Normalizer ----
        normalize_result = normalize_data(
            fetched_sources=fetched,
        )
        if normalize_result.get("status") == "error":
            return self._fail(
                f"Normalization failed: {normalize_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        normalized = normalize_result.get("normalized", {})

        # ---- Stage 5: Freshness Checker ----
        freshness_result = check_freshness(
            fetched_sources=fetched,
        )
        if freshness_result.get("status") == "error":
            return self._fail(
                f"Freshness check failed: {freshness_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        freshness_reports = freshness_result.get("reports", {})

        # ---- Stage 6: Assemble collected data ----
        collected: dict[str, Any] = {}
        total_records = 0
        for src_data in fetched:
            src_name = src_data.get("source", "unknown")
            records = normalized.get(src_name, src_data.get("records", []))
            count = len(records)
            total_records += count
            collected[src_name] = {
                "records": records,
                "count": count,
            }

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_collection_result(
            collected=collected,
            total_records=total_records,
            freshness=freshness_reports,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "collected": collected,
                "total_records": total_records,
                "freshness": freshness_reports,
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
