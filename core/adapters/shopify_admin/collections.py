"""Shopify collections — smart + custom + product joins.

Shopify's collection model has three related resources:

  * ``smart_collection`` — rule-based ("all products tagged
    ``summer`` under $50"). Auto-populates as products match
    the rules. API: ``/smart_collections.json``.
  * ``custom_collection`` — manually curated. API:
    ``/custom_collections.json``. (Shopify Admin UI calls
    these "Collections — manual".)
  * ``collect`` — the join row between a ``custom_collection``
    and a ``product``. Smart collections don't use collects.
    API: ``/collects.json``.

Before this wave, collection setup lived in
``execution/store_configurator._setup_collections`` (one-shot
bootstrap, GraphQL-flavoured). This module is the unified
REST surface for ongoing collection management — adding
products to an existing collection, renaming, reordering,
etc. — so engines other than the configurator can touch
collections too (the winback engine needs "all VIP buyers'
favourite products" as a smart collection; the ads engine
needs "new arrivals" to live update).
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.collections",
)


class SmartCollections:
    """Rule-driven collection CRUD."""

    @staticmethod
    def list_collections(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        title: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if title:
            params["title"] = str(title)
        result = client.get(
            "smart_collections.json", params=params,
        )
        rows = result.get("smart_collections") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        collection_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"smart_collections/{collection_id}.json",
        )
        col = result.get("smart_collection")
        if not isinstance(col, dict):
            raise ShopifyAdminError(
                f"smart_collection {collection_id} "
                "not returned",
                path=(
                    f"smart_collections/{collection_id}.json"
                ),
            )
        return col

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        title: str,
        rules: list[dict[str, Any]],
        disjunctive: bool = False,
        body_html: str | None = None,
        published: bool = True,
        sort_order: str = "best-selling",
    ) -> dict[str, Any]:
        """Create a smart collection.

        ``rules`` — list of ``{column, relation, condition}``
        dicts. Shopify's rule columns include ``tag``,
        ``type``, ``vendor``, ``variant_price``,
        ``variant_inventory``, etc. Example:

            [{"column": "tag", "relation": "equals",
              "condition": "winner"}]

        ``disjunctive=True`` means OR between rules
        (default AND).
        ``sort_order`` — Shopify-accepted values: ``alpha-asc``,
        ``alpha-desc``, ``best-selling``, ``created`` (oldest
        first), ``created-desc``, ``manual``, ``price-asc``,
        ``price-desc``.
        """
        if not title:
            raise ValueError("title: required")
        if not rules:
            raise ValueError(
                "rules: non-empty list required (use "
                "CustomCollections for manual curation)",
            )
        valid_sort = {
            "alpha-asc", "alpha-desc", "best-selling",
            "created", "created-desc", "manual",
            "price-asc", "price-desc",
        }
        if sort_order not in valid_sort:
            raise ValueError(
                f"sort_order must be one of {sorted(valid_sort)}",
            )
        col: dict[str, Any] = {
            "title": title,
            "rules": rules,
            "disjunctive": bool(disjunctive),
            "published": bool(published),
            "sort_order": sort_order,
        }
        if body_html is not None:
            col["body_html"] = str(body_html)
        result = client.post(
            "smart_collections.json", {"smart_collection": col},
        )
        created = result.get("smart_collection")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "smart_collection not returned by create",
                path="smart_collections.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        collection_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"smart_collections/{collection_id}.json",
            {"smart_collection": {
                "id": int(collection_id), **fields,
            }},
        )
        updated = result.get("smart_collection")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "smart_collection not returned by update",
                path=(
                    f"smart_collections/{collection_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        collection_id: int | str,
    ) -> None:
        client.delete(
            f"smart_collections/{collection_id}.json",
        )


class CustomCollections:
    """Manually-curated collection CRUD. Products attach via
    ``Collects`` (below)."""

    @staticmethod
    def list_collections(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        title: str | None = None,
        published_status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if title:
            params["title"] = str(title)
        if published_status:
            params["published_status"] = str(published_status)
        result = client.get(
            "custom_collections.json", params=params,
        )
        rows = result.get("custom_collections") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        collection_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"custom_collections/{collection_id}.json",
        )
        col = result.get("custom_collection")
        if not isinstance(col, dict):
            raise ShopifyAdminError(
                f"custom_collection {collection_id} "
                "not returned",
                path=(
                    f"custom_collections/{collection_id}.json"
                ),
            )
        return col

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        title: str,
        body_html: str | None = None,
        published: bool = True,
        sort_order: str = "manual",
        template_suffix: str | None = None,
    ) -> dict[str, Any]:
        if not title:
            raise ValueError("title: required")
        col: dict[str, Any] = {
            "title": title,
            "published": bool(published),
            "sort_order": sort_order,
        }
        if body_html is not None:
            col["body_html"] = str(body_html)
        if template_suffix:
            col["template_suffix"] = str(template_suffix)
        result = client.post(
            "custom_collections.json",
            {"custom_collection": col},
        )
        created = result.get("custom_collection")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "custom_collection not returned by create",
                path="custom_collections.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        collection_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"custom_collections/{collection_id}.json",
            {"custom_collection": {
                "id": int(collection_id), **fields,
            }},
        )
        updated = result.get("custom_collection")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "custom_collection not returned by update",
                path=(
                    f"custom_collections/{collection_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        collection_id: int | str,
    ) -> None:
        client.delete(
            f"custom_collections/{collection_id}.json",
        )


class Collects:
    """Product ↔ custom-collection joins. Smart collections
    don't have collects — their members are derived from
    rules."""

    @staticmethod
    def list_collects(
        client: ShopifyAdminClient,
        *,
        collection_id: int | str | None = None,
        product_id: int | str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List join rows. Filters: by ``collection_id`` (all
        products in this collection) or by ``product_id``
        (all collections this product is in)."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if collection_id is not None:
            params["collection_id"] = int(collection_id)
        if product_id is not None:
            params["product_id"] = int(product_id)
        result = client.get("collects.json", params=params)
        rows = result.get("collects") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        product_id: int | str,
        collection_id: int | str,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Add a product to a custom collection.
        ``position`` — 1-based; Shopify reorders the collection
        if provided. Omit for "append to end"."""
        body: dict[str, Any] = {
            "collect": {
                "product_id": int(product_id),
                "collection_id": int(collection_id),
            },
        }
        if position is not None:
            body["collect"]["position"] = int(position)
        result = client.post("collects.json", body)
        created = result.get("collect")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "collect not returned by create",
                path="collects.json",
                body=str(result),
            )
        return created

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        collect_id: int | str,
    ) -> None:
        client.delete(f"collects/{collect_id}.json")

    @staticmethod
    def remove_product(
        client: ShopifyAdminClient,
        *,
        product_id: int | str,
        collection_id: int | str,
    ) -> bool:
        """Convenience: find the collect for this
        (product, collection) pair + delete it. Returns
        True if a row was removed, False if no matching
        collect existed (§4b.D — idempotent)."""
        rows = Collects.list_collects(
            client,
            product_id=product_id,
            limit=250,
        )
        target = str(collection_id)
        for row in rows:
            if str(row.get("collection_id") or "") == target:
                Collects.delete(client, row["id"])
                return True
        return False
