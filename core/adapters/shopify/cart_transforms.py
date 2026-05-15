"""ShopifyCartTransformsAdapter — register Function-based cart transformations.

Cart transforms are Shopify Function-backed extensions that fire when
a cart is loaded and let the Function expand or rewrite line items
before checkout. The two canonical use cases:

  * **Bundle expansion.** A "Camping Starter Pack" SKU at $99 expands
    into the 4 constituent SKUs (tent, lantern, sleeping bag, mat) in
    the cart so inventory drains correctly and the customer sees what
    they're getting.
  * **Custom-name decoration.** Line items get a custom title /
    properties decoration based on cart context (engraving, monogram,
    "Anniversary special", …).

ShopAI's bundling engine + creative engine both want this surface to
ship configurable cart-time logic without writing theme code. Like
the payment/delivery customisations, the actual transformation logic
lives inside a Shopify Function the merchant's app deploys; this
adapter just attaches the Function to the cart pipeline.

Capabilities (CRUD on the registration record itself; Function code
is deployed via shopify-cli):

  * ``SHOPIFY_CREATE_CART_TRANSFORM`` — register a transform.
  * ``SHOPIFY_LIST_CART_TRANSFORMS``  — list registered transforms.
  * ``SHOPIFY_DELETE_CART_TRANSFORM`` — unregister.

There is no update mutation in the schema — the canonical edit path
is delete + recreate. Engines that want to flip a transform's config
re-register with a new Function or new metafield blob.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CART_TRANSFORM_FIELDS = """
id
functionId
blockOnFailure
""".strip()


_CREATE_CART_TRANSFORM_MUTATION = f"""
mutation cartTransformCreate(
  $functionId: String!,
  $blockOnFailure: Boolean,
  $metafields: [MetafieldInput!]
) {{
  cartTransformCreate(
    functionId: $functionId,
    blockOnFailure: $blockOnFailure,
    metafields: $metafields
  ) {{
    cartTransform {{
      {_CART_TRANSFORM_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_LIST_CART_TRANSFORMS_QUERY = f"""
query cartTransforms($first: Int!, $after: String) {{
  cartTransforms(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CART_TRANSFORM_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_DELETE_CART_TRANSFORM_MUTATION = """
mutation cartTransformDelete($id: ID!) {
  cartTransformDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyCartTransformsAdapter(ShopifyBaseAdapter):
    name = "shopify_cart_transforms"
    capabilities = {
        Capability.SHOPIFY_CREATE_CART_TRANSFORM,
        Capability.SHOPIFY_LIST_CART_TRANSFORMS,
        Capability.SHOPIFY_DELETE_CART_TRANSFORM,
    }
    required_scopes = frozenset({"write_cart_transforms"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_CART_TRANSFORM:
            return self._create(params)
        if capability == Capability.SHOPIFY_LIST_CART_TRANSFORMS:
            return self._list(params)
        if capability == Capability.SHOPIFY_DELETE_CART_TRANSFORM:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        function_id = params.get("function_id") or params.get("functionId")
        if not isinstance(function_id, str) or not function_id.strip():
            raise AdapterValidationError(
                "shopify_cart_transforms",
                "'function_id' is required — cart transforms are "
                "Shopify-Function-backed; the merchant's app must "
                "have a registered Function",
            )
        block_on_failure = bool(params.get("block_on_failure", False))
        metafields = self._build_metafields(params.get("metafields"))

        variables: dict[str, Any] = {
            "functionId": function_id.strip(),
            "blockOnFailure": block_on_failure,
        }
        if metafields:
            variables["metafields"] = metafields

        data = self._gql(_CREATE_CART_TRANSFORM_MUTATION, variables)
        self._check_user_errors(data, "cartTransformCreate")
        payload = data.get("cartTransformCreate") or {}
        node = payload.get("cartTransform") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_CART_TRANSFORM,
            data={
                "id": node.get("id", "") or "",
                "function_id": node.get("functionId", "") or "",
                "block_on_failure": bool(node.get("blockOnFailure", False)),
            },
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_cart_transforms",
                "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_CART_TRANSFORMS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("cartTransforms") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        transforms: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            transforms.append({
                "id": node.get("id", "") or "",
                "function_id": node.get("functionId", "") or "",
                "block_on_failure": bool(node.get("blockOnFailure", False)),
            })
        return self._success(
            Capability.SHOPIFY_LIST_CART_TRANSFORMS,
            data={
                "cart_transforms": transforms,
                "count": len(transforms),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        transform_id = params.get("id") or params.get("cart_transform_id")
        if not isinstance(transform_id, str) or not transform_id.strip():
            raise AdapterValidationError(
                "shopify_cart_transforms",
                "'id' (Shopify GID for the cart transform) is required",
            )
        data = self._gql(_DELETE_CART_TRANSFORM_MUTATION, {
            "id": transform_id.strip(),
        })
        self._check_user_errors(data, "cartTransformDelete")
        payload = data.get("cartTransformDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CART_TRANSFORM,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_metafields(raw: Any) -> list[dict[str, Any]]:
        """Convert ShopAI's friendly metafields list into MetafieldInput
        shape. Numeric values are coerced to strings per Shopify
        metafield convention.

        Friendly form::

            [{"namespace": "$app:bundle",
              "key":       "bundle_skus",
              "type":      "json",
              "value":     ["sku-1", "sku-2"]}]
        """
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise AdapterValidationError(
                "shopify_cart_transforms",
                "'metafields' must be a list of "
                "{namespace, key, type, value} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, mf in enumerate(raw):
            if not isinstance(mf, dict):
                raise AdapterValidationError(
                    "shopify_cart_transforms",
                    f"metafields[{i}] must be a dict",
                )
            ns = mf.get("namespace") or "shopai"
            key = mf.get("key")
            mf_type = mf.get("type") or "single_line_text_field"
            value = mf.get("value")
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    "shopify_cart_transforms",
                    f"metafields[{i}] missing 'key'",
                )
            if value is None:
                raise AdapterValidationError(
                    "shopify_cart_transforms",
                    f"metafields[{i}] missing 'value'",
                )
            # Shopify always wants the value as a string. JSON-coerce
            # complex values (lists / dicts) so engines can pass
            # native Python types.
            if isinstance(value, str):
                value_str = value
            elif isinstance(value, bool):
                value_str = "true" if value else "false"
            elif isinstance(value, (int, float)):
                value_str = str(value)
            else:
                import json as _json
                try:
                    value_str = _json.dumps(value)
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        "shopify_cart_transforms",
                        f"metafields[{i}] value not JSON-serialisable",
                    ) from exc
            out.append({
                "namespace": ns,
                "key": key,
                "type": mf_type,
                "value": value_str,
            })
        return out
