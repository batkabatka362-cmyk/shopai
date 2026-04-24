"""Shopify products — unified catalog CRUD.

Replaces the scattered product-write paths
(``execution/shopify/product_creator.py``,
``execution/shopify/product_updater.py``,
``execution/shopify_store_manager.py``,
``execution/shopify_automation.py``) with a single
resource-per-class API under the unified admin client.

Existing call sites keep working — this module is additive.
Migration happens incrementally as each execution path
gets re-wired.

Classes:
  * ``Products`` — products + variants (embedded)
  * ``Variants`` — variant-only CRUD for targeted updates
  * ``ProductImages`` — image CRUD (URL-based, server-
    downloaded by Shopify)
  * ``ProductMetafields`` — per-product metafields
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.products",
)


class Products:
    """Product CRUD. Variants + images can be inlined via
    ``create`` / ``update`` or managed through their own
    classes for targeted ops."""

    @staticmethod
    def list_products(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        status: str = "any",
        ids: list[int | str] | None = None,
        since_id: int | str | None = None,
        handle: str = "",
        vendor: str = "",
        product_type: str = "",
        fields: str = "",
    ) -> list[dict[str, Any]]:
        """``status``: any / active / archived / draft.
        ``handle`` filter pinpoints one product by URL slug."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
            "status": status,
        }
        if ids:
            params["ids"] = ",".join(str(i) for i in ids)
        if since_id is not None:
            params["since_id"] = str(since_id)
        if handle:
            params["handle"] = handle
        if vendor:
            params["vendor"] = vendor
        if product_type:
            params["product_type"] = product_type
        if fields:
            params["fields"] = fields
        result = client.get("products.json", params=params)
        rows = result.get("products") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, product_id: int | str,
        *, fields: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        result = client.get(
            f"products/{product_id}.json",
            params=params or None,
        )
        product = result.get("product")
        if not isinstance(product, dict):
            raise ShopifyAdminError(
                f"product {product_id} not returned",
                path=f"products/{product_id}.json",
            )
        return product

    @staticmethod
    def count(
        client: ShopifyAdminClient,
        *, status: str = "any",
    ) -> int:
        result = client.get(
            "products/count.json",
            params={"status": status},
        )
        return int(result.get("count") or 0)

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        title: str,
        body_html: str = "",
        vendor: str = "",
        product_type: str = "",
        tags: list[str] | None = None,
        status: str = "draft",
        variants: list[dict[str, Any]] | None = None,
        images: list[dict[str, Any]] | None = None,
        options: list[dict[str, Any]] | None = None,
        published: bool | None = None,
    ) -> dict[str, Any]:
        """Create a product. ``status`` starts draft by default
        so callers don't accidentally publish an un-finalised
        catalog entry. Flip to ``active`` once images, price,
        inventory are all set.

        ``variants`` accepts Shopify's inline variant shape;
        minimum each needs is ``price`` + one ``option1`` (or
        omit for a single-variant product).
        """
        if not title:
            raise ValueError("title: required")
        body: dict[str, Any] = {
            "product": {"title": str(title), "status": status},
        }
        p = body["product"]
        if body_html:
            p["body_html"] = body_html
        if vendor:
            p["vendor"] = vendor
        if product_type:
            p["product_type"] = product_type
        if tags:
            p["tags"] = ", ".join(str(t) for t in tags)
        if variants:
            p["variants"] = list(variants)
        if images:
            p["images"] = list(images)
        if options:
            p["options"] = list(options)
        if published is not None:
            p["published"] = bool(published)
        result = client.post("products.json", body)
        created = result.get("product")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "product not returned by create",
                path="products.json", body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        product_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial update — only pass fields you want to
        change. Shopify requires ``id`` on payload — injected.
        Writable fields: title, body_html, vendor,
        product_type, tags, status, published, variants,
        images, options, metafields.
        """
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"products/{product_id}.json",
            {"product": {"id": int(product_id), **fields}},
        )
        updated = result.get("product")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "product not returned by update",
                path=f"products/{product_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        product_id: int | str,
    ) -> None:
        """Permanent delete. Soft-alternative is ``update(
        status='archived')``."""
        client.delete(f"products/{product_id}.json")

    # ── Tag helpers ────────────────────────────────────

    @staticmethod
    def add_tags(
        client: ShopifyAdminClient,
        product_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("tags: non-empty list required")
        existing = Products.get(client, product_id)
        current = _split_tags(existing.get("tags", ""))
        merged = sorted({
            *current, *(t.strip() for t in tags if t),
        })
        return Products.update(
            client, product_id,
            fields={"tags": ", ".join(merged)},
        )

    @staticmethod
    def remove_tags(
        client: ShopifyAdminClient,
        product_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("tags: non-empty list required")
        drop = {t.strip().lower() for t in tags if t}
        existing = Products.get(client, product_id)
        current = _split_tags(existing.get("tags", ""))
        kept = sorted(
            t for t in current
            if t.strip().lower() not in drop
        )
        return Products.update(
            client, product_id,
            fields={"tags": ", ".join(kept)},
        )

    # ── Status helpers ─────────────────────────────────

    @staticmethod
    def publish(
        client: ShopifyAdminClient,
        product_id: int | str,
    ) -> dict[str, Any]:
        return Products.update(
            client, product_id,
            fields={"status": "active", "published": True},
        )

    @staticmethod
    def unpublish(
        client: ShopifyAdminClient,
        product_id: int | str,
    ) -> dict[str, Any]:
        return Products.update(
            client, product_id,
            fields={"status": "draft", "published": False},
        )

    @staticmethod
    def archive(
        client: ShopifyAdminClient,
        product_id: int | str,
    ) -> dict[str, Any]:
        return Products.update(
            client, product_id,
            fields={"status": "archived"},
        )


class Variants:
    """Product-variant CRUD. Variants are addressable
    independently of their parent product — useful when
    updating just a price or SKU without re-sending the
    full product payload."""

    @staticmethod
    def list_variants(
        client: ShopifyAdminClient,
        product_id: int | str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"products/{product_id}/variants.json",
            params={"limit": max(1, min(int(limit), 250))},
        )
        rows = result.get("variants") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        variant_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"variants/{variant_id}.json",
        )
        v = result.get("variant")
        if not isinstance(v, dict):
            raise ShopifyAdminError(
                f"variant {variant_id} not returned",
                path=f"variants/{variant_id}.json",
            )
        return v

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        product_id: int | str,
        *,
        price: float | str,
        sku: str = "",
        option1: str = "",
        option2: str = "",
        option3: str = "",
        inventory_management: str = "shopify",
        inventory_quantity: int | None = None,
        compare_at_price: float | str | None = None,
        weight: float | None = None,
        weight_unit: str = "kg",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "variant": {
                "price": (
                    f"{float(price):.2f}"
                    if not isinstance(price, str) else price
                ),
                "inventory_management": inventory_management,
            },
        }
        v = body["variant"]
        if sku:
            v["sku"] = str(sku)
        if option1:
            v["option1"] = str(option1)
        if option2:
            v["option2"] = str(option2)
        if option3:
            v["option3"] = str(option3)
        if inventory_quantity is not None:
            v["inventory_quantity"] = int(inventory_quantity)
        if compare_at_price is not None:
            v["compare_at_price"] = (
                f"{float(compare_at_price):.2f}"
                if not isinstance(compare_at_price, str)
                else compare_at_price
            )
        if weight is not None:
            v["weight"] = float(weight)
            v["weight_unit"] = weight_unit
        result = client.post(
            f"products/{product_id}/variants.json", body,
        )
        created = result.get("variant")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "variant not returned by create",
                path=(
                    f"products/{product_id}/variants.json"
                ),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        variant_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"variants/{variant_id}.json",
            {"variant": {
                "id": int(variant_id), **fields,
            }},
        )
        updated = result.get("variant")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "variant not returned by update",
                path=f"variants/{variant_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        product_id: int | str,
        variant_id: int | str,
    ) -> None:
        """Shopify requires the parent product_id in the
        delete path."""
        client.delete(
            f"products/{product_id}/"
            f"variants/{variant_id}.json",
        )

    @staticmethod
    def set_price(
        client: ShopifyAdminClient,
        variant_id: int | str,
        price: float | str,
        *,
        compare_at_price: float | str | None = None,
    ) -> dict[str, Any]:
        """Targeted price update. Absolute — idempotent per
        §4b.D."""
        fields: dict[str, Any] = {
            "price": (
                f"{float(price):.2f}"
                if not isinstance(price, str) else price
            ),
        }
        if compare_at_price is not None:
            fields["compare_at_price"] = (
                f"{float(compare_at_price):.2f}"
                if not isinstance(compare_at_price, str)
                else compare_at_price
            )
        return Variants.update(
            client, variant_id, fields=fields,
        )


class ProductImages:
    """Product-image CRUD. URLs only — Shopify's server
    downloads + re-hosts. Base64 ``attachment`` uploads
    left to direct callers (rare in our flows)."""

    @staticmethod
    def list_images(
        client: ShopifyAdminClient,
        product_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"products/{product_id}/images.json",
        )
        rows = result.get("images") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        product_id: int | str,
        *,
        src: str,
        alt: str = "",
        position: int | None = None,
        variant_ids: list[int | str] | None = None,
    ) -> dict[str, Any]:
        """``src`` must be publicly fetchable HTTPS URL.
        Shopify server-downloads + re-hosts to its CDN.
        ``variant_ids`` attaches the image to those specific
        variants (for swatch pickers)."""
        if not src:
            raise ValueError("src: non-empty URL required")
        body: dict[str, Any] = {
            "image": {"src": src},
        }
        img = body["image"]
        if alt:
            img["alt"] = str(alt)
        if position is not None:
            img["position"] = int(position)
        if variant_ids:
            img["variant_ids"] = [
                int(v) for v in variant_ids
            ]
        result = client.post(
            f"products/{product_id}/images.json", body,
        )
        created = result.get("image")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "image not returned by create",
                path=f"products/{product_id}/images.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        product_id: int | str,
        image_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"products/{product_id}/images/{image_id}.json",
            {"image": {
                "id": int(image_id), **fields,
            }},
        )
        updated = result.get("image")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "image not returned by update",
                path=(
                    f"products/{product_id}/"
                    f"images/{image_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        product_id: int | str,
        image_id: int | str,
    ) -> None:
        client.delete(
            f"products/{product_id}/images/{image_id}.json",
        )


class ProductMetafields:
    """Per-product metafield CRUD. Metafields on other
    resources (customer, order, shop, etc.) follow the same
    pattern — dedicated modules when we need them."""

    @staticmethod
    def list_metafields(
        client: ShopifyAdminClient,
        product_id: int | str,
        *, namespace: str = "",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if namespace:
            params["namespace"] = namespace
        result = client.get(
            f"products/{product_id}/metafields.json",
            params=params or None,
        )
        rows = result.get("metafields") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        product_id: int | str,
        *,
        namespace: str,
        key: str,
        value: Any,
        value_type: str = "single_line_text_field",
        description: str = "",
    ) -> dict[str, Any]:
        """``value_type`` examples:
        ``single_line_text_field`` / ``number_integer`` /
        ``json`` / ``boolean`` / ``date`` / ``url``.

        For JSON values pass a dict — helper serialises."""
        if not namespace or not key:
            raise ValueError(
                "namespace + key required",
            )
        if isinstance(value, (dict, list)):
            import json as _json
            value_str = _json.dumps(value)
        else:
            value_str = str(value)
        body: dict[str, Any] = {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value_str,
                "type": value_type,
            },
        }
        if description:
            body["metafield"]["description"] = description
        result = client.post(
            f"products/{product_id}/metafields.json", body,
        )
        created = result.get("metafield")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "metafield not returned by create",
                path=(
                    f"products/{product_id}/metafields.json"
                ),
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        product_id: int | str,
        metafield_id: int | str,
        *,
        value: Any,
        value_type: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(value, (dict, list)):
            import json as _json
            value_str = _json.dumps(value)
        else:
            value_str = str(value)
        body: dict[str, Any] = {
            "metafield": {
                "id": int(metafield_id),
                "value": value_str,
            },
        }
        if value_type:
            body["metafield"]["type"] = value_type
        result = client.put(
            f"products/{product_id}/"
            f"metafields/{metafield_id}.json",
            body,
        )
        updated = result.get("metafield")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "metafield not returned by update",
                path=(
                    f"products/{product_id}/"
                    f"metafields/{metafield_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        product_id: int | str,
        metafield_id: int | str,
    ) -> None:
        client.delete(
            f"products/{product_id}/"
            f"metafields/{metafield_id}.json",
        )


def _split_tags(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [
        t.strip() for t in str(raw).split(",") if t.strip()
    ]
