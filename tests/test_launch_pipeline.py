"""Smoke tests for the Goal-Driven launch pipeline.

Covers the contract every step must honour:
  • optional steps skip cleanly without polluting context
  • hard-required steps abort the pipeline on failure
  • the result envelope serialises to JSON without TypeErrors
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workflows.launch import LaunchPipeline, LaunchGoal


class TestLaunchPipelineSmoke(unittest.TestCase):
    def setUp(self) -> None:
        # Strip any real Shopify creds from the env so tests run hermetically
        for k in (
            "SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY",
            "CJ_DROPSHIPPING_API_KEY", "AUTODS_API_KEY",
            "META_ADS_ACCESS_TOKEN", "META_ADS_ACCOUNT_ID",
            "META_ADS_PIXEL_ID", "META_ADS_PAGE_ID",
        ):
            os.environ.pop(k, None)

    def test_pipeline_aborts_when_shopify_creds_missing(self) -> None:
        """shopify_create is hard-required: missing env vars must
        produce a 'failed' result with the failure surfaced clearly."""
        goal = LaunchGoal(
            manual_payload={
                "title": "Test Product",
                "price_usd": 5.0,
                "supplier_url": "https://example.com/sku",
                "gallery_urls": ["https://cdn.example.com/img.jpg"],
            },
            target_price=29.99,
        )
        result = LaunchPipeline().run(goal)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failed_step, "shopify_create")
        self.assertIn("SHOPAI_SHOPIFY", result.failure_reason or "")

    def test_pipeline_aborts_when_no_source_supplied(self) -> None:
        """No alibaba_url / spy_url / supplier_sku / manual_payload =
        source step must skip and pipeline aborts later."""
        goal = LaunchGoal()  # nothing supplied
        result = LaunchPipeline().run(goal)
        # source step skips, downstream hard-required steps will then fail
        steps_by_name = {s.name: s for s in result.steps}
        self.assertEqual(steps_by_name["source"].status, "skipped")
        # We expect either failed or partial — never silently 'complete'
        self.assertIn(result.status, ("failed", "partial"))

    def test_optional_step_skip_does_not_break_pipeline(self) -> None:
        """supplier + ads_launch are optional — their skip must not
        block media / content / shopify_create from succeeding."""
        # Mock ProductCreator to skip the real Shopify HTTP call
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"
        os.environ["SHOPAI_SHOPIFY_KEY"] = "shpat_fake"
        with patch(
            "execution.shopify.product_creator.ProductCreator.create_product",
            return_value={
                "status": "created",
                "product": {"id": 123, "handle": "test-product"},
            },
        ):
            goal = LaunchGoal(
                manual_payload={
                    "title": "Smoke Test",
                    "price_usd": 5.0,
                    "supplier_url": "https://example.com/sku",
                    "gallery_urls": ["https://cdn.example.com/img.jpg"],
                },
                target_price=29.99,
            )
            result = LaunchPipeline().run(goal)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.shopify_product_id, 123)
        self.assertEqual(result.shopify_handle, "test-product")
        # supplier + ads_launch must be skipped (no creds)
        skipped = {s.name for s in result.steps if s.status == "skipped"}
        self.assertIn("supplier", skipped)
        self.assertIn("ads_launch", skipped)

    def test_result_serialises_to_json(self) -> None:
        import json
        goal = LaunchGoal(manual_payload={"title": "T"})
        result = LaunchPipeline().run(goal)
        # Should produce a JSON-serialisable dict
        try:
            json.dumps(result.as_dict())
        except (TypeError, ValueError) as exc:
            self.fail(f"LaunchResult.as_dict() not JSON-safe: {exc}")


class TestPriceComputation(unittest.TestCase):
    """The price math is deterministic — no LLM, fully testable."""

    def test_target_above_floor_used(self) -> None:
        from workflows.launch.steps.shopify_create import ShopifyCreateStep
        # source price $5, margin floor 30 % → floor = $6.50
        # target $29.99 > floor → use $29.99
        price = ShopifyCreateStep._compute_price(5.0, 29.99, 0.30)
        self.assertEqual(price, 29.99)

    def test_target_below_floor_promoted(self) -> None:
        from workflows.launch.steps.shopify_create import ShopifyCreateStep
        # source price $20, margin 50 % → floor = $30
        # target $25 < floor → use $30
        price = ShopifyCreateStep._compute_price(20.0, 25.0, 0.50)
        self.assertEqual(price, 30.0)

    def test_no_target_falls_back_to_floor_or_min(self) -> None:
        from workflows.launch.steps.shopify_create import ShopifyCreateStep
        # source $4, margin 30 % → floor = $5.20
        # but min price = $9.99 → use $9.99
        price = ShopifyCreateStep._compute_price(4.0, None, 0.30)
        self.assertEqual(price, 9.99)


if __name__ == "__main__":
    unittest.main()
