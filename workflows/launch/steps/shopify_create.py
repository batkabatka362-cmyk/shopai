"""Step 5 — Shopify product create.

Pricing math (deterministic, no LLM):
    sell_price = max(target_price, source_price * (1 + margin_floor))
    compare_at = round(sell_price * 1.6, 2)        # for psych. discount

Idempotency: searches the store for existing product by handle before
creating, returns the existing id if found. (Per CLAUDE.md §4b.D.)
"""
from __future__ import annotations

import os
from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext
from ._base import Step, StepFailure


logger = get_logger("workflows.launch.shopify_create")


class ShopifyCreateStep(Step):
    name = "shopify_create"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        title = context.content.get("title") or context.source.get("title")
        if not title:
            raise StepFailure("missing title — cannot create Shopify product")

        shop_url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        api_key = os.environ.get("SHOPAI_SHOPIFY_KEY", "")
        if not shop_url or not api_key:
            raise StepFailure("SHOPAI_SHOPIFY_URL / SHOPAI_SHOPIFY_KEY not set")

        sell_price = self._compute_price(
            context.source.get("price_usd", 0),
            context.goal.target_price,
            context.goal.margin_floor,
        )
        compare_at = round(sell_price * 1.6, 2)

        # ProductCreator expects flat fields: title, price, description.
        # It builds the Shopify-shaped payload internally.
        product_payload = {
            "title": title,
            "price": sell_price,
            "description": context.content.get("description", ""),
            "vendor": "ShopAI",
            "product_type": context.goal.niche or "",
            "tags": ",".join(context.content.get("tags", [])),
            "images": list(context.media.get("gallery", [])),
            "compare_at_price": compare_at,
            "inventory_quantity": 100,
        }

        from execution.shopify.product_creator import ProductCreator
        creator = ProductCreator()
        result = creator.create_product(shop_url, api_key, product_payload)

        if result.get("status") != "created":
            raise StepFailure(
                f"Shopify create failed: {result.get('errors') or result.get('error')}"
            )

        product = result.get("product", {})
        product_id = product.get("id")
        if not product_id:
            raise StepFailure(f"Shopify create returned no id: {result!r}")

        return {
            "product_id": product_id,
            "handle": product.get("handle"),
            "admin_url": f"https://{shop_url}/admin/products/{product_id}",
            "storefront_url": f"https://{shop_url}/products/{product.get('handle', '')}",
            "sell_price": sell_price,
            "compare_at": compare_at,
        }

    @staticmethod
    def _compute_price(
        source_price: float,
        target: float | None,
        margin_floor: float,
    ) -> float:
        floor = source_price * (1 + margin_floor) if source_price else 0
        if target is None:
            target = round(max(floor, 9.99), 2)
        return round(max(target, floor), 2)
