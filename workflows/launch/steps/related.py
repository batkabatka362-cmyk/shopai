"""Step — Related products (upsell / cross-sell).

After the product is live on Shopify, look at the rest of the catalog,
pick the 4 most complementary products, and stamp their ids on the
new product as a ``shopai/related_product_ids`` metafield. Storefront
themes or Rebuy-style apps can render this list to lift AOV.

Scoring (deterministic, CLAUDE.md §4b.A):
  +3  shares a tag with the new product
  +2  sits in the same product_type
  +1  price within 50-150 % of the new product price

Uses the Shopify Admin API directly (no adapter abstraction needed
for a single GET). Soft-fails with StepSkip on any error — related
products are a nice-to-have.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from utils.logger import get_logger

from ..context import LaunchContext
from ._base import Step, StepSkip


logger = get_logger("workflows.launch.related")


class RelatedProductsStep(Step):
    name = "related"
    optional = True

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        product_id = context.shopify_product.get("product_id")
        sell_price = context.shopify_product.get("sell_price") or 0.0
        if not product_id:
            raise StepSkip("no shopify product yet — skip related")

        shop = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        try:
            from core.auth.token_resolver import (
                resolve_access_token,
            )
            token = resolve_access_token(shop)
        except Exception:  # noqa: BLE001
            token = os.environ.get(
                "SHOPAI_SHOPIFY_KEY", "",
            )
        if not shop or not token:
            raise StepSkip("shopify creds missing for related fetch")

        tags = set(t.strip().lower() for t in context.content.get("tags", []) if t)
        niche = (context.goal.niche or "").lower()

        candidates = self._fetch_products(shop, token, limit=150)
        if not candidates:
            raise StepSkip("no existing products to relate against")

        scored = self._score(candidates, tags, niche, sell_price, exclude=product_id)
        top = scored[:4]
        if not top:
            raise StepSkip("no related candidates scored > 0")

        related_ids = [p["id"] for p in top]
        metafield_status = self._write_metafield(shop, token, product_id, related_ids)

        return {
            "related_product_ids": related_ids,
            "related_summary": [
                {"id": p["id"], "title": p.get("title", "")[:60], "score": p["_score"]}
                for p in top
            ],
            "metafield": metafield_status,
        }

    @staticmethod
    def _fetch_products(shop: str, token: str, limit: int) -> list[dict[str, Any]]:
        url = (
            f"https://{shop}/admin/api/2024-01/products.json?"
            + urllib.parse.urlencode({
                "limit": min(max(limit, 1), 250),
                "fields": "id,title,tags,product_type,variants",
            })
        )
        req = urllib.request.Request(
            url,
            headers={"X-Shopify-Access-Token": token, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            logger.debug("related fetch failed: %s", exc)
            return []
        return data.get("products") or []

    @staticmethod
    def _score(
        products: list[dict[str, Any]],
        tags: set[str],
        niche: str,
        price: float,
        exclude: int,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for p in products:
            if p.get("id") == exclude:
                continue
            score = 0
            p_tags = {t.strip().lower() for t in (p.get("tags") or "").split(",") if t.strip()}
            if tags & p_tags:
                score += 3
            ptype = (p.get("product_type") or "").lower()
            if ptype and niche and (niche in ptype or ptype in niche):
                score += 2
            variants = p.get("variants") or []
            if price > 0 and variants:
                try:
                    vp = float(variants[0].get("price") or 0)
                    if 0.5 * price <= vp <= 1.5 * price:
                        score += 1
                except (ValueError, TypeError):
                    pass
            if score > 0:
                p_copy = dict(p)
                p_copy["_score"] = score
                scored.append(p_copy)
        scored.sort(key=lambda p: (-p["_score"], p.get("id", 0)))
        return scored

    @staticmethod
    def _write_metafield(
        shop: str, token: str, product_id: int, related_ids: list[int],
    ) -> str:
        body = json.dumps({
            "metafield": {
                "namespace": "shopai",
                "key": "related_product_ids",
                "value": json.dumps(related_ids),
                "type": "json",
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://{shop}/admin/api/2024-01/products/{product_id}/metafields.json",
            data=body,
            headers={
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                return "written"
        except urllib.error.HTTPError as exc:
            return f"error:{exc.code}"
        except urllib.error.URLError as exc:
            return f"error:{exc.reason}"
