"""ShopifyCollectionMembershipAdapter — collection membership writes.

Companion to ``collections.py`` (LIST/GET/CREATE/UPDATE/DELETE).
The membership write surface is the friendly path for engines
that want to *attach* products to manual collections without
re-saving the entire collection record.

ShopAI's creative + merchandising engines lean on this:

  * **Auto-tag winners.** Pricing engine flags a product that
    crossed its margin threshold; the creative engine adds it to
    the "Top Movers" hand-curated collection so it surfaces on
    the homepage.
  * **Sale rotation.** Promotion engine builds a "Memorial Day"
    sale by adding ~30 products to an existing manual collection,
    then removes them after the campaign window closes.
  * **Featured-products reorder.** Storefront merchandising
    engine moves a flagship product to position 0 (or shuffles
    several) without rebuilding the collection.

Capabilities:

  * ``SHOPIFY_ADD_PRODUCTS_TO_COLLECTION``      —
    collectionAddProducts (synchronous, returns the collection).
  * ``SHOPIFY_REMOVE_PRODUCTS_FROM_COLLECTION`` —
    collectionRemoveProducts (returns a Job, runs async).
  * ``SHOPIFY_REORDER_COLLECTION_PRODUCTS``     —
    collectionReorderProducts (returns a Job, runs async).

All three mutations: Pattern A (id at field level, NOT inside
an Input dict). Pattern F (UserError variants — no code field).

Pattern C (codified): collectionAddProducts / Remove / Reorder
only work on MANUAL collections. Smart / automatic collections
build their membership rules-based and reject explicit
membership writes with "Cannot manually add products to a smart
collection". The adapter doesn't pre-check (would require a
separate read), letting Shopify return the userError verbatim.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ADD_PRODUCTS_MUTATION = """
mutation collectionAddProducts($id: ID!, $productIds: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $productIds) {
    collection {
      id
      title
      handle
      productsCount {
        count
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_REMOVE_PRODUCTS_MUTATION = """
mutation collectionRemoveProducts($id: ID!, $productIds: [ID!]!) {
  collectionRemoveProducts(id: $id, productIds: $productIds) {
    job {
      id
      done
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_REORDER_PRODUCTS_MUTATION = """
mutation collectionReorderProducts(
  $id: ID!,
  $moves: [MoveInput!]!
) {
  collectionReorderProducts(id: $id, moves: $moves) {
    job {
      id
      done
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyCollectionMembershipAdapter(ShopifyBaseAdapter):
    name = "shopify_collection_membership"
    capabilities = {
        Capability.SHOPIFY_ADD_PRODUCTS_TO_COLLECTION,
        Capability.SHOPIFY_REMOVE_PRODUCTS_FROM_COLLECTION,
        Capability.SHOPIFY_REORDER_COLLECTION_PRODUCTS,
    }
    required_scopes = frozenset({"write_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_ADD_PRODUCTS_TO_COLLECTION:
            return self._add(params)
        if capability == Capability.SHOPIFY_REMOVE_PRODUCTS_FROM_COLLECTION:
            return self._remove(params)
        if capability == Capability.SHOPIFY_REORDER_COLLECTION_PRODUCTS:
            return self._reorder(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Add ────────────────────────────────────────────────────────

    def _add(self, params: dict[str, Any]) -> Any:
        collection_id = self._extract_collection_id(params)
        product_ids = self._extract_product_ids(params)
        data = self._gql(_ADD_PRODUCTS_MUTATION, {
            "id": collection_id, "productIds": product_ids,
        })
        self._check_user_errors(data, "collectionAddProducts")
        payload = data.get("collectionAddProducts") or {}
        collection = payload.get("collection") or {}
        return self._success(
            Capability.SHOPIFY_ADD_PRODUCTS_TO_COLLECTION,
            data={
                "collection_id": (
                    collection.get("id", "")
                    if isinstance(collection, dict) else ""
                ) or "",
                "title": (
                    collection.get("title", "")
                    if isinstance(collection, dict) else ""
                ) or "",
                "handle": (
                    collection.get("handle", "")
                    if isinstance(collection, dict) else ""
                ) or "",
                "products_count": self._extract_count(
                    collection.get("productsCount")
                    if isinstance(collection, dict) else None
                ),
                "added_count": len(product_ids),
            },
        )

    # ── Remove ─────────────────────────────────────────────────────

    def _remove(self, params: dict[str, Any]) -> Any:
        collection_id = self._extract_collection_id(params)
        product_ids = self._extract_product_ids(params)
        data = self._gql(_REMOVE_PRODUCTS_MUTATION, {
            "id": collection_id, "productIds": product_ids,
        })
        self._check_user_errors(data, "collectionRemoveProducts")
        payload = data.get("collectionRemoveProducts") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_REMOVE_PRODUCTS_FROM_COLLECTION,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
                "removed_count": len(product_ids),
            },
        )

    # ── Reorder ────────────────────────────────────────────────────

    def _reorder(self, params: dict[str, Any]) -> Any:
        collection_id = self._extract_collection_id(params)
        moves = self._build_moves(params.get("moves"))
        data = self._gql(_REORDER_PRODUCTS_MUTATION, {
            "id": collection_id, "moves": moves,
        })
        self._check_user_errors(data, "collectionReorderProducts")
        payload = data.get("collectionReorderProducts") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_REORDER_COLLECTION_PRODUCTS,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
                "moves_count": len(moves),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_collection_id(self, params: dict[str, Any]) -> str:
        cid = (
            params.get("id")
            or params.get("collection_id")
            or params.get("collectionId")
        )
        if not isinstance(cid, str) or not cid.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the collection) is required",
            )
        return cid.strip()

    def _extract_product_ids(
        self, params: dict[str, Any],
    ) -> list[str]:
        raw = (
            params.get("product_ids")
            or params.get("productIds")
            or params.get("products")
        )
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'product_ids' must be a non-empty list of product GIDs",
            )
        if not all(isinstance(p, str) for p in raw):
            raise AdapterValidationError(
                self.name,
                "'product_ids' must contain only GID strings",
            )
        ids = [p.strip() for p in raw if p.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'product_ids' contained only blanks",
            )
        return ids

    def _build_moves(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'moves' must be a non-empty list of "
                "{id, new_position} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, m in enumerate(raw):
            if not isinstance(m, dict):
                raise AdapterValidationError(
                    self.name, f"moves[{i}] must be a dict",
                )
            pid = m.get("id") or m.get("product_id")
            new_pos = (
                m.get("new_position")
                if "new_position" in m else m.get("newPosition")
            )
            if not isinstance(pid, str) or not pid.strip():
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}] missing 'id' (product GID)",
                )
            if new_pos is None:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}] missing 'new_position' (zero-indexed int)",
                )
            try:
                pos_int = int(new_pos)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}].new_position must be a non-negative int",
                ) from exc
            if pos_int < 0:
                raise AdapterValidationError(
                    self.name,
                    f"moves[{i}].new_position must be >= 0",
                )
            out.append({
                "id": pid.strip(),
                "newPosition": str(pos_int),
            })
        return out

    @staticmethod
    def _extract_count(node: Any) -> int:
        # Pattern D: productsCount is the {count} wrapper, not a
        # bare int in 2024-01+.
        if isinstance(node, dict):
            try:
                return int(node.get("count", 0) or 0)
            except (TypeError, ValueError):
                return 0
        try:
            return int(node or 0)
        except (TypeError, ValueError):
            return 0
