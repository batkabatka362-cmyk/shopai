"""ShopifyPaymentCustomizationsAdapter + ShopifyDeliveryCustomizationsAdapter
— checkout-time payment / delivery method customizations.

These two surfaces are structurally identical — both are
Shopify-Function-backed customizations that reorder, hide, or
rename methods at checkout based on cart contents. The adapter pair
shares this file because the GraphQL mutations differ only in name
prefix (``paymentCustomizationCreate`` vs
``deliveryCustomizationCreate``) and the friendly call shape is the
same. Splitting them into separate files would duplicate ~80% of
the adapter code; sharing the helpers keeps both consistent and the
test surface single-anchored.

Both customizations REQUIRE a deployed Shopify Function — engines
that just want to "hide a payment method when cart > $X" still need
the merchant's app to have a registered Function (Function code is
deployed via shopify-cli; this adapter just attaches it to the
checkout flow). Without a Function ID the create calls reject.

Capabilities (each adapter exposes 3):

  Payment side:
    * ``SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION``
    * ``SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS``
    * ``SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION``

  Delivery side:
    * ``SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION``
    * ``SHOPIFY_LIST_DELIVERY_CUSTOMIZATIONS``
    * ``SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION``

Friendly call shape (same for both)::

    {
      "title": "Hide AmEx for orders > $1000",
      "function_id": "12345-67890",          # the registered Function
      "enabled": True,                       # default True
      "metafields": [                        # optional — Function config
          {"namespace": "$app:my-config",
           "key": "threshold",
           "type": "number_decimal",
           "value": "1000.00"},
      ],
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates (parameterised by mutation prefix) ─────────────


def _create_mutation(prefix: str) -> str:
    """Build the create-customization mutation for the given prefix
    (``payment`` or ``delivery``). Both share the same input shape.

    Note: the argument name follows Shopify's "input named after the
    type" convention — ``paymentCustomization`` for payment,
    ``deliveryCustomization`` for delivery — NOT the generic
    ``input`` (caught live as 'missing required arguments:
    paymentCustomization' and 'doesn't accept argument input').
    """
    arg_name = f"{prefix}Customization"
    return f"""
mutation {prefix}CustomizationCreate(
  ${arg_name}: {prefix.capitalize()}CustomizationInput!
) {{
  {prefix}CustomizationCreate({arg_name}: ${arg_name}) {{
    {prefix}Customization {{
      id
      title
      enabled
      functionId
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


def _list_query(prefix: str) -> str:
    """Build the list query (``paymentCustomizations`` /
    ``deliveryCustomizations``)."""
    return f"""
query {prefix}Customizations($first: Int!, $after: String) {{
  {prefix}Customizations(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        id
        title
        enabled
        functionId
      }}
    }}
  }}
}}
""".strip()


def _delete_mutation(prefix: str) -> str:
    return f"""
mutation {prefix}CustomizationDelete($id: ID!) {{
  {prefix}CustomizationDelete(id: $id) {{
    deletedId
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class _CustomizationsBase(ShopifyBaseAdapter):
    """Shared logic for the payment / delivery customisations pair.

    Subclasses set ``_prefix`` (``"payment"`` or ``"delivery"``) and
    declare their own ``capabilities`` set; this base wires the
    GraphQL queries and the friendly-shape validation in one place.
    """

    _prefix: str = ""  # subclass override
    _create_cap: Capability = Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION
    _list_cap: Capability = Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS
    _delete_cap: Capability = Capability.SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == self._create_cap:
            return self._create(params)
        if capability == self._list_cap:
            return self._list(params)
        if capability == self._delete_cap:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        customization_input = self._build_input(params)
        # GraphQL variable name follows Shopify's "input named after
        # the type" convention (paymentCustomization /
        # deliveryCustomization), not generic ``input``.
        var_name = f"{self._prefix}Customization"
        data = self._gql(
            _create_mutation(self._prefix),
            {var_name: customization_input},
        )
        mutation_name = f"{self._prefix}CustomizationCreate"
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        node = payload.get(f"{self._prefix}Customization") or {}
        return self._success(
            self._create_cap,
            data={
                "id": node.get("id", "") or "",
                "title": node.get("title", "") or "",
                "enabled": bool(node.get("enabled", False)),
                "function_id": node.get("functionId", "") or "",
            },
        )

    def _build_input(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name,
                "'title' is required (non-empty string)",
            )
        function_id = params.get("function_id") or params.get("functionId")
        if not isinstance(function_id, str) or not function_id.strip():
            raise AdapterValidationError(
                self.name,
                "'function_id' is required — both customisation surfaces "
                "are Shopify-Function-backed; the merchant's app must "
                "have a registered Function",
            )
        out: dict[str, Any] = {
            "title": title.strip(),
            "functionId": function_id.strip(),
            "enabled": bool(params.get("enabled", True)),
        }
        metafields = params.get("metafields")
        if metafields is not None:
            if not isinstance(metafields, list):
                raise AdapterValidationError(
                    self.name,
                    "'metafields' must be a list of "
                    "{namespace, key, type, value} dicts",
                )
            mf_out: list[dict[str, Any]] = []
            for i, mf in enumerate(metafields):
                if not isinstance(mf, dict):
                    raise AdapterValidationError(
                        self.name, f"metafields[{i}] must be a dict",
                    )
                ns = mf.get("namespace") or "shopai"
                key = mf.get("key")
                value = mf.get("value")
                mf_type = mf.get("type") or "single_line_text_field"
                if not isinstance(key, str) or not key.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"metafields[{i}] missing 'key'",
                    )
                if value is None:
                    raise AdapterValidationError(
                        self.name,
                        f"metafields[{i}] missing 'value'",
                    )
                # Shopify always wants the value as a string.
                mf_out.append({
                    "namespace": ns,
                    "key": key,
                    "type": mf_type,
                    "value": str(value) if not isinstance(value, str) else value,
                })
            if mf_out:
                out["metafields"] = mf_out
        return out

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
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_list_query(self._prefix), {
            "first": limit,
            "after": cursor,
        })
        envelope_field = f"{self._prefix}Customizations"
        envelope = data.get(envelope_field) or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        items: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            items.append({
                "id": node.get("id", "") or "",
                "title": node.get("title", "") or "",
                "enabled": bool(node.get("enabled", False)),
                "function_id": node.get("functionId", "") or "",
            })
        return self._success(
            self._list_cap,
            data={
                "customizations": items,
                "count": len(items),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        customization_id = (
            params.get("id") or params.get("customization_id")
        )
        if not isinstance(customization_id, str) or not customization_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customization) is required",
            )
        data = self._gql(_delete_mutation(self._prefix), {
            "id": customization_id.strip(),
        })
        mutation_name = f"{self._prefix}CustomizationDelete"
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        return self._success(
            self._delete_cap,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )


class ShopifyPaymentCustomizationsAdapter(_CustomizationsBase):
    name = "shopify_payment_customizations"
    _prefix = "payment"
    _create_cap = Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION
    _list_cap = Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS
    _delete_cap = Capability.SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION
    capabilities = {
        Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION,
        Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS,
        Capability.SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION,
    }


class ShopifyDeliveryCustomizationsAdapter(_CustomizationsBase):
    name = "shopify_delivery_customizations"
    _prefix = "delivery"
    _create_cap = Capability.SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION
    _list_cap = Capability.SHOPIFY_LIST_DELIVERY_CUSTOMIZATIONS
    _delete_cap = Capability.SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION
    capabilities = {
        Capability.SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION,
        Capability.SHOPIFY_LIST_DELIVERY_CUSTOMIZATIONS,
        Capability.SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION,
    }
