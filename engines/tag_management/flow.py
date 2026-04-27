"""Tag Management Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Auto Tagger → Taxonomy Builder →
  Tag Optimizer → Consistency Checker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, existing_tags, taxonomy}, meta, error}
  Output: {status, data: {tags, taxonomy_updates, optimization_suggestions, consistency_score}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .auto_tagger import auto_tag
from .taxonomy_builder import build_taxonomy
from .tag_optimizer import optimize_tags
from .consistency_checker import check_consistency
from .memory_reader import read_past_tag_runs
from .memory_writer import write_tag_result
from engines._shopify_hydrator import hydrate


class TagManagementEngine:
    """Tag Management Engine — orchestrator only, no logic."""

    ENGINE_NAME = "tag_management"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        existing_tags = data.get("existing_tags", [])
        taxonomy = data.get("taxonomy", {})

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Products list is required", 0.0)

        _past = read_past_tag_runs(limit=5)

        tag_result = auto_tag(products=products, existing_tags=existing_tags)
        if tag_result.get("status") == "error":
            return self._fail(f"Auto-tagging failed: {tag_result.get('error')}", time.monotonic() - start)
        tag_assignments = tag_result.get("assignments", [])

        tax_result = build_taxonomy(tag_assignments=tag_assignments, existing_taxonomy=taxonomy)
        if tax_result.get("status") == "error":
            return self._fail(f"Taxonomy building failed: {tax_result.get('error')}", time.monotonic() - start)
        taxonomy_updates = tax_result.get("taxonomy", {})

        opt_result = optimize_tags(tag_assignments=tag_assignments, taxonomy=taxonomy_updates)
        if opt_result.get("status") == "error":
            return self._fail(f"Tag optimization failed: {opt_result.get('error')}", time.monotonic() - start)
        optimization_suggestions = opt_result.get("suggestions", [])

        con_result = check_consistency(tag_assignments=tag_assignments, taxonomy=taxonomy_updates)
        if con_result.get("status") == "error":
            return self._fail(f"Consistency check failed: {con_result.get('error')}", time.monotonic() - start)
        consistency_score = con_result.get("consistency_score", 0.0)

        _write = write_tag_result(tags=tag_assignments, consistency_score=consistency_score)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "tags": tag_assignments,
                "taxonomy_updates": taxonomy_updates,
                "optimization_suggestions": optimization_suggestions,
                "consistency_score": consistency_score,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
