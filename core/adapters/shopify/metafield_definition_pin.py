"""ShopifyMetafieldDefinitionPinAdapter — pin/unpin metafield definitions.

Companion to ``metafield_definitions.py`` (LIST/GET/CREATE/
UPDATE/DELETE on the definition itself). Pinning controls
whether a definition surfaces at the top of the resource's
metafield drawer in admin — pinned definitions get the
prominent "Quick edit" treatment, unpinned ones get hidden in
the "All metafields" overflow.

ShopAI's content engines use this to keep operator UX coherent:

  * **Promote a new field after rollout.** When the team adds a
    "fabric_composition" definition to Product, the engine
    pins it once the data is fully populated so reviewers see
    it without scrolling.
  * **Demote retired fields.** Internal-only fields that were
    pinned for a campaign get unpinned when the campaign closes;
    they stay queryable but stop cluttering the operator UI.

Capabilities:

  * ``SHOPIFY_PIN_METAFIELD_DEFINITION``   — metafieldDefinitionPin.
  * ``SHOPIFY_UNPIN_METAFIELD_DEFINITION`` — metafieldDefinitionUnpin.

Both mutations accept EITHER a direct ``definitionId`` GID OR a
composite ``identifier: {ownerType, key, namespace?}``. The
adapter exposes both forms — pass ``definition_id`` directly,
or supply ``owner_type`` + ``key`` (with optional ``namespace``)
to identify by triple.

UserError variants are
``MetafieldDefinitionPinUserError`` /
``MetafieldDefinitionUnpinUserError``, both with ``code``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DEFINITION_FIELDS = """
id
name
key
namespace
ownerType
pinnedPosition
""".strip()


_PIN_DEFINITION_MUTATION = f"""
mutation metafieldDefinitionPin(
  $definitionId: ID,
  $identifier: MetafieldDefinitionIdentifierInput
) {{
  metafieldDefinitionPin(
    definitionId: $definitionId, identifier: $identifier
  ) {{
    pinnedDefinition {{
      {_DEFINITION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UNPIN_DEFINITION_MUTATION = f"""
mutation metafieldDefinitionUnpin(
  $definitionId: ID,
  $identifier: MetafieldDefinitionIdentifierInput
) {{
  metafieldDefinitionUnpin(
    definitionId: $definitionId, identifier: $identifier
  ) {{
    unpinnedDefinition {{
      {_DEFINITION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_OWNER_TYPES = {
    "API_PERMISSION", "ARTICLE", "BLOG", "CARTTRANSFORM",
    "COLLECTION", "COMPANY", "COMPANY_LOCATION", "CUSTOMER",
    "DELIVERY_CUSTOMIZATION", "DISCOUNT", "DRAFTORDER",
    "FULFILLMENT_CONSTRAINT_RULE", "GIFT_CARD_TRANSACTION",
    "LOCATION", "MARKET", "ORDER", "ORDER_ROUTING_LOCATION_RULE",
    "PAGE", "PAYMENT_CUSTOMIZATION", "PRODUCT", "PRODUCTVARIANT",
    "SELLING_PLAN", "SHOP", "VALIDATION",
}


class ShopifyMetafieldDefinitionPinAdapter(ShopifyBaseAdapter):
    name = "shopify_metafield_definition_pin"
    capabilities = {
        Capability.SHOPIFY_PIN_METAFIELD_DEFINITION,
        Capability.SHOPIFY_UNPIN_METAFIELD_DEFINITION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_PIN_METAFIELD_DEFINITION:
            return self._pin_or_unpin(
                params, _PIN_DEFINITION_MUTATION,
                "metafieldDefinitionPin", "pinnedDefinition",
                Capability.SHOPIFY_PIN_METAFIELD_DEFINITION,
            )
        if capability == Capability.SHOPIFY_UNPIN_METAFIELD_DEFINITION:
            return self._pin_or_unpin(
                params, _UNPIN_DEFINITION_MUTATION,
                "metafieldDefinitionUnpin", "unpinnedDefinition",
                Capability.SHOPIFY_UNPIN_METAFIELD_DEFINITION,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _pin_or_unpin(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        result_field: str,
        capability: Capability,
    ) -> Any:
        variables = self._build_variables(params)
        data = self._gql(mutation, variables)
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        return self._success(
            capability,
            data={
                "definition": self._normalise_definition(
                    payload.get(result_field) or {}
                ),
            },
        )

    # ── Variable builder ───────────────────────────────────────────

    def _build_variables(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        definition_id = (
            params.get("definition_id")
            or params.get("definitionId")
            or params.get("id")
        )
        owner_type = (
            params.get("owner_type") or params.get("ownerType")
        )
        key = params.get("key")
        namespace = params.get("namespace")

        # Accept either definition_id OR identifier triple, not both.
        # If both supplied, definition_id wins (more specific).
        if definition_id:
            if not isinstance(definition_id, str) or not definition_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'definition_id' must be a non-empty GID string",
                )
            return {
                "definitionId": definition_id.strip(),
                "identifier": None,
            }

        # Fall back to identifier triple.
        if not isinstance(owner_type, str) or not owner_type.strip():
            raise AdapterValidationError(
                self.name,
                "supply 'definition_id' OR an identifier triple "
                "('owner_type' + 'key', optional 'namespace')",
            )
        owner_up = owner_type.strip().upper()
        if owner_up not in _VALID_OWNER_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'owner_type' must be one of "
                f"{sorted(_VALID_OWNER_TYPES)}",
            )
        if not isinstance(key, str) or not key.strip():
            raise AdapterValidationError(
                self.name,
                "'key' is required when identifying by triple",
            )

        identifier: dict[str, Any] = {
            "ownerType": owner_up,
            "key": key.strip(),
        }
        if namespace is not None:
            if not isinstance(namespace, str):
                raise AdapterValidationError(
                    self.name, "'namespace' must be a string",
                )
            namespace = namespace.strip()
            if namespace:
                identifier["namespace"] = namespace
        return {
            "definitionId": None,
            "identifier": identifier,
        }

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_definition(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        try:
            position = int(node.get("pinnedPosition") or 0)
        except (TypeError, ValueError):
            position = 0
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "key": node.get("key", "") or "",
            "namespace": node.get("namespace", "") or "",
            "owner_type": node.get("ownerType", "") or "",
            "pinned_position": position,
        }
