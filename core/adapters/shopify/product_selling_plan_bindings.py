"""ShopifyProductSellingPlanBindingsAdapter — product↔selling-plan-group.

The existing ``selling_plan_groups.py`` adapter manages selling plan
groups themselves (the catalogue of subscription cadences and
discounts). The BINDINGS — which products and variants each group
applies to — were never wired up. ShopAI's subscription engine writes
these whenever:

  * A new product is launched and should immediately be eligible for
    the merchant's standard "subscribe and save 10%" plan.
  * A product is being retired from the subscription program but
    kept on the storefront for one-time purchase.
  * A specific variant (e.g. the 12-pack but not the 6-pack) is
    being scoped into or out of a tier-specific plan.

Capabilities:

  * ``SHOPIFY_PRODUCT_JOIN_SELLING_PLAN_GROUPS``  —
    productJoinSellingPlanGroups. Pattern A: product id at field
    level + list of group GIDs.
  * ``SHOPIFY_PRODUCT_LEAVE_SELLING_PLAN_GROUPS`` —
    productLeaveSellingPlanGroups. Same shape.
  * ``SHOPIFY_PRODUCT_VARIANT_JOIN_SELLING_PLAN_GROUPS`` —
    productVariantJoinSellingPlanGroups. Variant-level binding for
    fine-grained scope.
  * ``SHOPIFY_PRODUCT_VARIANT_LEAVE_SELLING_PLAN_GROUPS`` —
    productVariantLeaveSellingPlanGroups.

Friendly call shape::

    {"id":                      "gid://shopify/Product/123",
     "selling_plan_group_ids":  ["gid://shopify/SellingPlanGroup/1",
                                 "gid://shopify/SellingPlanGroup/2"]}

Pattern A — id at field level on every mutation.
Pattern F — all four mutations use ``SellingPlanGroupUserError``
(HAS code — introspection confirmed: ['code', 'field', 'message']).
Selection keeps it.

Pattern E note: gated by ``write_products`` /
``write_selling_plans``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


def _make_mutation(op_name: str, resource_type: str) -> str:
    return f"""
mutation {op_name}(
  $id: ID!,
  $sellingPlanGroupIds: [ID!]!
) {{
  {op_name}(id: $id, sellingPlanGroupIds: $sellingPlanGroupIds) {{
    {resource_type} {{
      id
      title
      sellingPlanGroupCount
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_PRODUCT_JOIN_MUTATION = _make_mutation(
    "productJoinSellingPlanGroups", "product",
)
_PRODUCT_LEAVE_MUTATION = _make_mutation(
    "productLeaveSellingPlanGroups", "product",
)


def _make_variant_mutation(op_name: str) -> str:
    return f"""
mutation {op_name}(
  $id: ID!,
  $sellingPlanGroupIds: [ID!]!
) {{
  {op_name}(id: $id, sellingPlanGroupIds: $sellingPlanGroupIds) {{
    productVariant {{
      id
      title
      sellingPlanGroupCount
      product {{
        id
        title
      }}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VARIANT_JOIN_MUTATION = _make_variant_mutation(
    "productVariantJoinSellingPlanGroups",
)
_VARIANT_LEAVE_MUTATION = _make_variant_mutation(
    "productVariantLeaveSellingPlanGroups",
)


class ShopifyProductSellingPlanBindingsAdapter(ShopifyBaseAdapter):
    name = "shopify_product_selling_plan_bindings"
    capabilities = {
        Capability.SHOPIFY_PRODUCT_JOIN_SELLING_PLAN_GROUPS,
        Capability.SHOPIFY_PRODUCT_LEAVE_SELLING_PLAN_GROUPS,
        Capability.SHOPIFY_PRODUCT_VARIANT_JOIN_SELLING_PLAN_GROUPS,
        Capability.SHOPIFY_PRODUCT_VARIANT_LEAVE_SELLING_PLAN_GROUPS,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_PRODUCT_JOIN_SELLING_PLAN_GROUPS:
            return self._call(
                params,
                _PRODUCT_JOIN_MUTATION,
                "productJoinSellingPlanGroups",
                "product",
                Capability.SHOPIFY_PRODUCT_JOIN_SELLING_PLAN_GROUPS,
            )
        if capability == \
                Capability.SHOPIFY_PRODUCT_LEAVE_SELLING_PLAN_GROUPS:
            return self._call(
                params,
                _PRODUCT_LEAVE_MUTATION,
                "productLeaveSellingPlanGroups",
                "product",
                Capability.SHOPIFY_PRODUCT_LEAVE_SELLING_PLAN_GROUPS,
            )
        if capability == \
                Capability.SHOPIFY_PRODUCT_VARIANT_JOIN_SELLING_PLAN_GROUPS:
            return self._call(
                params,
                _VARIANT_JOIN_MUTATION,
                "productVariantJoinSellingPlanGroups",
                "productVariant",
                Capability.SHOPIFY_PRODUCT_VARIANT_JOIN_SELLING_PLAN_GROUPS,
            )
        if capability == \
                Capability.SHOPIFY_PRODUCT_VARIANT_LEAVE_SELLING_PLAN_GROUPS:
            return self._call(
                params,
                _VARIANT_LEAVE_MUTATION,
                "productVariantLeaveSellingPlanGroups",
                "productVariant",
                Capability.SHOPIFY_PRODUCT_VARIANT_LEAVE_SELLING_PLAN_GROUPS,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _call(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        resource_key: str,
        capability: Capability,
    ) -> Any:
        resource_id = self._extract_id(params, resource_key)
        group_ids = self._build_group_ids(params)

        data = self._gql(mutation, {
            "id": resource_id,
            "sellingPlanGroupIds": group_ids,
        })
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        return self._success(
            capability,
            data={
                "resource": self._normalise(
                    payload.get(resource_key) or {},
                    resource_key=resource_key,
                ),
                "selling_plan_group_ids": group_ids,
                "count": len(group_ids),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(
        self, params: dict[str, Any], resource_key: str,
    ) -> str:
        kind = (
            "Product" if resource_key == "product"
            else "ProductVariant"
        )
        resource_id = (
            params.get("id")
            or params.get(f"{resource_key}_id")
            or params.get(f"{resource_key}Id")
        )
        if not isinstance(resource_id, str) or \
                not resource_id.strip():
            raise AdapterValidationError(
                self.name,
                f"'id' (Shopify GID for the {kind}) is required",
            )
        return resource_id.strip()

    def _build_group_ids(
        self, params: dict[str, Any],
    ) -> list[str]:
        raw = (
            params.get("selling_plan_group_ids")
            or params.get("sellingPlanGroupIds")
            or params.get("group_ids")
        )
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'selling_plan_group_ids' must be a non-empty list "
                "of SellingPlanGroup GIDs",
            )
        cleaned = []
        for i, v in enumerate(raw):
            if not isinstance(v, str) or not v.strip():
                raise AdapterValidationError(
                    self.name,
                    f"'selling_plan_group_ids[{i}]' must be a "
                    "non-empty GID string",
                )
            cleaned.append(v.strip())
        return cleaned

    @staticmethod
    def _normalise(
        node: dict[str, Any],
        *,
        resource_key: str,
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        out: dict[str, Any] = {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "selling_plan_group_count": int(
                node.get("sellingPlanGroupCount", 0) or 0,
            ),
        }
        if resource_key == "productVariant":
            product = node.get("product") or {}
            out["product_id"] = (
                product.get("id", "")
                if isinstance(product, dict) else ""
            ) or ""
            out["product_title"] = (
                product.get("title", "")
                if isinstance(product, dict) else ""
            ) or ""
        return out
