"""ShopifyGenericTagsAdapter — add/remove tags on any taggable resource.

Companions: most resource adapters (orders, customers, products,
draft orders, etc.) expose tag operations as resource-specific
mutations (orderUpdate with `tags`, customerUpdate with `tags`,
…). Those flows replace the entire tag set; this adapter wraps
the GENERIC ``tagsAdd`` / ``tagsRemove`` mutations that mutate
any taggable resource by id without round-tripping the rest of
the record.

Why a separate adapter:

  * **Atomic delta updates.** ``tagsAdd`` / ``tagsRemove``
    operate on the delta — add these N tags, remove those M —
    without touching the rest of the resource. Resource-specific
    update mutations require sending the full new tag set,
    which races with concurrent edits.
  * **Cross-resource fan-out.** Tagging engines (segmentation,
    fraud-flag, campaign-eligibility) need to apply the same
    label across products + customers + orders. Generic tagsAdd
    means one engine path instead of three resource-specific
    branches.

Capabilities:

  * ``SHOPIFY_ADD_TAGS``    — tagsAdd. Pattern A: id + tags both
    at field level.
  * ``SHOPIFY_REMOVE_TAGS`` — tagsRemove. Same shape as add.

Pattern F: both mutations use the typed ``UserError`` (no
``code``).

Both work on any resource that implements the ``Node`` interface
AND is tagged in Shopify's data model (Customer, Product, Order,
DraftOrder, Article, Blog, Page, etc.). The adapter doesn't
type-check the GID prefix — Shopify's userError surfaces a
clear message when the target isn't taggable.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ADD_TAGS_MUTATION = """
mutation tagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_REMOVE_TAGS_MUTATION = """
mutation tagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyGenericTagsAdapter(ShopifyBaseAdapter):
    name = "shopify_generic_tags"
    capabilities = {
        Capability.SHOPIFY_ADD_TAGS,
        Capability.SHOPIFY_REMOVE_TAGS,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_ADD_TAGS:
            return self._mutate(
                params, _ADD_TAGS_MUTATION, "tagsAdd",
                Capability.SHOPIFY_ADD_TAGS,
            )
        if capability == Capability.SHOPIFY_REMOVE_TAGS:
            return self._mutate(
                params, _REMOVE_TAGS_MUTATION, "tagsRemove",
                Capability.SHOPIFY_REMOVE_TAGS,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _mutate(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        node_id = (
            params.get("id")
            or params.get("resource_id")
            or params.get("node_id")
        )
        if not isinstance(node_id, str) or not node_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the taggable resource — "
                "Customer/Product/Order/DraftOrder/Article/Blog/Page/...) "
                "is required",
            )
        tags = self._build_tags(params.get("tags"))

        data = self._gql(mutation, {
            "id": node_id.strip(),
            "tags": tags,
        })
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        node = payload.get("node") or {}
        return self._success(
            capability,
            data={
                "id": (
                    node.get("id", "")
                    if isinstance(node, dict) else ""
                ) or "",
                "tags": tags,
                "count": len(tags),
            },
        )

    def _build_tags(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'tags' must be a non-empty list of strings (or a "
                "single tag string)",
            )
        if not all(isinstance(t, str) for t in raw):
            raise AdapterValidationError(
                self.name, "'tags' must contain only strings",
            )
        cleaned = [t.strip() for t in raw if t.strip()]
        if not cleaned:
            raise AdapterValidationError(
                self.name, "'tags' contained only blanks",
            )
        return cleaned
