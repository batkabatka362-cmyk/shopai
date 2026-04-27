"""Catalog Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Category Organizer → Collection Builder →
  Tag Assigner → Catalog Validator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, categories, tags}, meta, error}
  Output: {status, data: {catalog, tag_assignments, validation, completeness_score}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .category_organizer import organize_categories
from .collection_builder import build_collections
from .tag_assigner import assign_tags
from .catalog_validator import validate_catalog
from .memory_reader import read_past_catalogs
from .memory_writer import write_catalog_result
from .shopify_hydrator import hydrate_products
from .shopify_applier import (
    apply_tag_assignments,
    enqueue_tag_assignments_for_approval,
)


class CatalogEngine:
    """Catalog Engine — orchestrator only, no logic."""

    ENGINE_NAME = "catalog"

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
        categories = data.get("categories", [])
        tags = data.get("tags", [])

        # Stage 0.5: Auto-hydrate products from Shopify when caller
        # didn't pre-fetch. Pass-through if non-empty; auto-fetch
        # via Capability.SHOPIFY_LIST_PRODUCTS otherwise. The
        # standard "Products list is required" guard still fires
        # when both supplied AND hydrated are empty.
        products = hydrate_products(
            products,
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Products list is required", 0.0)

        _past = read_past_catalogs(limit=5)

        cat_result = organize_categories(products=products, categories=categories)
        if cat_result.get("status") == "error":
            return self._fail(f"Category organization failed: {cat_result.get('error')}", time.monotonic() - start)
        organized_cats = cat_result.get("categories", {})

        coll_result = build_collections(products=products, categories=organized_cats)
        if coll_result.get("status") == "error":
            return self._fail(f"Collection building failed: {coll_result.get('error')}", time.monotonic() - start)
        collections = coll_result.get("collections", [])

        tag_result = assign_tags(products=products, available_tags=tags)
        if tag_result.get("status") == "error":
            return self._fail(f"Tag assignment failed: {tag_result.get('error')}", time.monotonic() - start)
        tag_assignments = tag_result.get("assignments", [])

        # Stage 3.5: Push tag assignments to Shopify (opt-in).
        # Three paths:
        #
        #   data.apply_tags=False (default) → all stamped
        #     "apply disabled by caller" (no API call, no queue)
        #   data.apply_tags=True + data.require_approval=False
        #     → SHOPIFY_ADD_TAGS immediately (legacy direct path)
        #   data.apply_tags=True + data.require_approval=True
        #     → enqueue each assignment to core.approval; merchant
        #       approves via /api/pending-actions before any
        #       SHOPIFY_ADD_TAGS call lands
        #
        # All three paths mutate the assignments in place so the
        # engine output's ``tag_assignments`` shape stays uniform;
        # the queue path additionally stamps a ``pending_action_id``.
        # Per-assignment graceful fallback — one product's failure
        # doesn't stop the rest.
        apply_flag = bool(data.get("apply_tags", False))
        if apply_flag and data.get("require_approval") is True:
            tag_assignments = enqueue_tag_assignments_for_approval(
                tag_assignments, apply=apply_flag,
            )
        else:
            tag_assignments = apply_tag_assignments(
                tag_assignments, apply=apply_flag,
            )

        val_result = validate_catalog(products=products, categories=organized_cats, tag_assignments=tag_assignments)
        if val_result.get("status") == "error":
            return self._fail(f"Catalog validation failed: {val_result.get('error')}", time.monotonic() - start)
        validation = val_result.get("validation", {})
        completeness_score = val_result.get("completeness_score", 0.0)

        catalog = {"categories": organized_cats, "collections": collections}

        _write = write_catalog_result(catalog=catalog, completeness_score=completeness_score)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "catalog": catalog,
                "tag_assignments": tag_assignments,
                "validation": validation,
                "completeness_score": completeness_score,
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
