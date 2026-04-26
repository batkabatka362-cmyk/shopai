"""ShopifyStandardMetafieldDefinitionAdapter — enable pre-defined defs.

Companion to ``metafield_definitions.py`` (custom CRUD) and
``metafield_definition_pin.py`` (pin/unpin). Shopify ships a
curated list of "standard" metafield definitions
(``harmonized_system_code`` on Product, ``country_of_origin``
on ProductVariant, ``materials``, etc.) — definitions that are
common across stores and that Shopify maintains the schema for.

Activating one of these is different from creating a custom
definition: the merchant picks from the catalog (by GID OR by
namespace+key) and the schema is fixed by Shopify rather than
declared by the caller.

ShopAI's catalog-setup engine uses this when:

  * **Compliance lift.** New regulatory requirement says
    products must declare HS codes. Engine enables Shopify's
    standard ``custom.harmonized_system_code`` definition
    rather than rolling its own.
  * **Audit alignment.** Operator wants country-of-origin
    metafields to use the standard schema so 3PLs / customs
    brokers can read them via the documented Shopify shape.

Capability:

  * ``SHOPIFY_ENABLE_STANDARD_METAFIELD_DEFINITION`` —
    standardMetafieldDefinitionEnable. Pattern A: ownerType +
    the identifier (id OR namespace+key) all at field level.
    Optional ``pin`` flag controls whether the new definition
    is auto-pinned in the admin drawer.

UserError variant: ``StandardMetafieldDefinitionEnableUserError``
(has ``code``).

The full ``capabilities`` and ``access`` config args are
supported as pass-through dicts; engines that don't need them
can omit. Most callers will only set ``pin``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ENABLE_STANDARD_DEFINITION_MUTATION = """
mutation standardMetafieldDefinitionEnable(
  $ownerType: MetafieldOwnerType!,
  $id: ID,
  $namespace: String,
  $key: String,
  $pin: Boolean,
  $capabilities: MetafieldCapabilityCreateInput,
  $access: StandardMetafieldDefinitionAccessInput
) {
  standardMetafieldDefinitionEnable(
    ownerType: $ownerType,
    id: $id,
    namespace: $namespace,
    key: $key,
    pin: $pin,
    capabilities: $capabilities,
    access: $access
  ) {
    createdDefinition {
      id
      name
      key
      namespace
      ownerType
      pinnedPosition
      type {
        name
        category
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


# Same enum set as metafield_definition_pin.py.
_VALID_OWNER_TYPES = {
    "API_PERMISSION", "ARTICLE", "BLOG", "CARTTRANSFORM",
    "COLLECTION", "COMPANY", "COMPANY_LOCATION", "CUSTOMER",
    "DELIVERY_CUSTOMIZATION", "DISCOUNT", "DRAFTORDER",
    "FULFILLMENT_CONSTRAINT_RULE", "GIFT_CARD_TRANSACTION",
    "LOCATION", "MARKET", "ORDER", "ORDER_ROUTING_LOCATION_RULE",
    "PAGE", "PAYMENT_CUSTOMIZATION", "PRODUCT", "PRODUCTVARIANT",
    "SELLING_PLAN", "SHOP", "VALIDATION",
}


class ShopifyStandardMetafieldDefinitionAdapter(ShopifyBaseAdapter):
    name = "shopify_standard_metafield_definition"
    capabilities = {
        Capability.SHOPIFY_ENABLE_STANDARD_METAFIELD_DEFINITION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_ENABLE_STANDARD_METAFIELD_DEFINITION:
            return self._enable(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _enable(self, params: dict[str, Any]) -> Any:
        owner_type_raw = params.get("owner_type") or params.get("ownerType")
        if not isinstance(owner_type_raw, str) or \
                not owner_type_raw.strip():
            raise AdapterValidationError(
                self.name,
                f"'owner_type' is required — one of "
                f"{sorted(_VALID_OWNER_TYPES)}",
            )
        owner_type = owner_type_raw.strip().upper()
        if owner_type not in _VALID_OWNER_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'owner_type' must be one of "
                f"{sorted(_VALID_OWNER_TYPES)}",
            )

        # Identifier: either id GID OR namespace+key. Adapter accepts
        # both; if both supplied, id wins (more specific).
        std_id = params.get("id") or params.get("definition_id")
        namespace = params.get("namespace")
        key = params.get("key")

        if std_id is not None:
            if not isinstance(std_id, str) or not std_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'id' must be a non-empty StandardMetafieldDefinition "
                    "GID string",
                )
            id_arg: str | None = std_id.strip()
            namespace_arg: str | None = None
            key_arg: str | None = None
        else:
            if not isinstance(namespace, str) or not namespace.strip():
                raise AdapterValidationError(
                    self.name,
                    "supply 'id' OR ('namespace' + 'key') to identify "
                    "the standard definition",
                )
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    self.name,
                    "'key' is required when identifying by "
                    "namespace+key",
                )
            id_arg = None
            namespace_arg = namespace.strip()
            key_arg = key.strip()

        variables: dict[str, Any] = {
            "ownerType": owner_type,
            "id": id_arg,
            "namespace": namespace_arg,
            "key": key_arg,
            "pin": None,
            "capabilities": None,
            "access": None,
        }

        if "pin" in params and params["pin"] is not None:
            variables["pin"] = bool(params["pin"])

        capabilities_in = params.get("capabilities")
        if capabilities_in is not None:
            if not isinstance(capabilities_in, dict):
                raise AdapterValidationError(
                    self.name,
                    "'capabilities' must be a dict matching "
                    "MetafieldCapabilityCreateInput",
                )
            variables["capabilities"] = capabilities_in

        access_in = params.get("access")
        if access_in is not None:
            if not isinstance(access_in, dict):
                raise AdapterValidationError(
                    self.name,
                    "'access' must be a dict matching "
                    "StandardMetafieldDefinitionAccessInput",
                )
            variables["access"] = access_in

        data = self._gql(
            _ENABLE_STANDARD_DEFINITION_MUTATION, variables,
        )
        self._check_user_errors(
            data, "standardMetafieldDefinitionEnable",
        )
        payload = data.get("standardMetafieldDefinitionEnable") or {}
        return self._success(
            Capability.SHOPIFY_ENABLE_STANDARD_METAFIELD_DEFINITION,
            data={
                "definition": self._normalise_definition(
                    payload.get("createdDefinition") or {}
                ),
            },
        )

    @staticmethod
    def _normalise_definition(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        try:
            position = int(node.get("pinnedPosition") or 0)
        except (TypeError, ValueError):
            position = 0
        type_node = node.get("type") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "key": node.get("key", "") or "",
            "namespace": node.get("namespace", "") or "",
            "owner_type": node.get("ownerType", "") or "",
            "pinned_position": position,
            "type_name": (
                type_node.get("name", "")
                if isinstance(type_node, dict) else ""
            ) or "",
            "type_category": (
                type_node.get("category", "")
                if isinstance(type_node, dict) else ""
            ) or "",
        }
