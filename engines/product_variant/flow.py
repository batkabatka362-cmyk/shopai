"""Product Variant Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Variant Generator → SKU Builder →
  Price Mapper → Inventory Linker → Image Mapper → Variant Validator →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, options, exclusions, images, inventory_data}, meta, error}
  Output: {status, data: {variants, skus, prices, inventory, image_mappings, validation, ...}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .variant_generator import generate_variants
from .sku_builder import build_skus
from .price_mapper import map_prices
from .inventory_linker import link_inventory
from .image_mapper import map_images
from .variant_validator import validate_variants
from .memory_reader import read_variant_history
from .memory_writer import write_variant_record


class ProductVariantEngine:
    """Product Variant Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_variant"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full product variant pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            VariantOutput dict.
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

        product = data.get("product", {})
        options = data.get("options", [])
        exclusions = data.get("exclusions", [])
        images = data.get("images", [])
        inventory_data = data.get("inventory_data", [])

        if not product:
            return self._fail("Product is required", 0.0)
        if not options:
            return self._fail("Options list is required", 0.0)

        product_id = str(product.get("product_id", ""))
        product_code = str(product.get("product_code", ""))
        base_price = float(product.get("base_price", 0.0))

        if not product_code:
            return self._fail("Product code is required", 0.0)

        # ---- Stage 1: Read variant history (non-blocking) ----
        _history = read_variant_history(product_id=product_id, limit=5)

        # ---- Stage 2: Variant Generator ----
        gen_result = generate_variants(
            product=product,
            options=options,
            exclusions=exclusions,
        )
        if gen_result.get("status") == "error":
            return self._fail(
                f"Variant generation failed: {gen_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        variants = gen_result.get("variants", [])
        excluded_count = gen_result.get("excluded", 0)

        # ---- Stage 3: SKU Builder ----
        sku_result = build_skus(
            product_code=product_code,
            variants=variants,
        )
        if sku_result.get("status") == "error":
            return self._fail(
                f"SKU building failed: {sku_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        skus = sku_result.get("skus", [])

        # ---- Stage 4: Price Mapper ----
        price_result = map_prices(
            variants=variants,
            base_price=base_price,
            options=options,
        )
        if price_result.get("status") == "error":
            return self._fail(
                f"Price mapping failed: {price_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        prices = price_result.get("prices", [])

        # ---- Stage 5: Inventory Linker ----
        inv_result = link_inventory(
            variants=variants,
            skus=skus,
            inventory_data=inventory_data,
        )
        if inv_result.get("status") == "error":
            return self._fail(
                f"Inventory linking failed: {inv_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        inventory_links = inv_result.get("inventory", [])
        linked_count = inv_result.get("linked_count", 0)
        unlinked_count = inv_result.get("unlinked_count", 0)

        # ---- Stage 6: Image Mapper ----
        img_result = map_images(
            variants=variants,
            images=images,
        )
        if img_result.get("status") == "error":
            return self._fail(
                f"Image mapping failed: {img_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        image_mappings = img_result.get("mappings", [])

        # ---- Stage 7: Variant Validator ----
        val_result = validate_variants(
            variants=variants,
            skus=skus,
            prices=prices,
        )
        if val_result.get("status") == "error":
            return self._fail(
                f"Variant validation failed: {val_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        validation = {
            "is_valid": val_result.get("is_valid", False),
            "duplicate_skus": val_result.get("duplicate_skus", []),
            "price_anomalies": val_result.get("price_anomalies", []),
            "warnings": val_result.get("warnings", []),
        }

        # ---- Stage 8: Memory Writer (non-fatal) ----
        _write_result = write_variant_record(
            product_id=product_id,
            product_code=product_code,
            variants=variants,
            skus=skus,
            prices=prices,
            validation=validation,
            total_variants=len(variants),
            excluded_count=excluded_count,
        )

        # ---- Stage 9: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "variants": variants,
                "skus": skus,
                "prices": prices,
                "inventory": inventory_links,
                "linked_count": linked_count,
                "unlinked_count": unlinked_count,
                "image_mappings": image_mappings,
                "validation": validation,
                "total_variants": len(variants),
                "excluded_count": excluded_count,
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
