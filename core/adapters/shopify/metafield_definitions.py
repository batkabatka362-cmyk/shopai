"""ShopifyMetafieldDefinitionsAdapter — metafield schema management.

Companion to ``metafield.py`` (which writes metafield VALUES).
Metafield definitions are the SCHEMA: the namespace+key pairs are
declared up front with a type, validation rules, and admin-UI
visibility flags. Without a definition, metafields work but are
invisible in the admin UI and don't get type-checked.

ShopAI's engines benefit by:

  * Registering structured-data shapes once (e.g. AI fraud score,
    learning-engine state, brain decision blob) so the merchant
    can see them in the admin and the catalog filters can use them.
  * Migrating existing freeform metafields into typed definitions
    (better filtering performance + UI surface).

Capabilities:

  * ``SHOPIFY_LIST_METAFIELD_DEFINITIONS``  — paginated list per
    owner type (PRODUCT, ORDER, CUSTOMER, ...).
  * ``SHOPIFY_CREATE_METAFIELD_DEFINITION`` — register a new
    definition.
  * ``SHOPIFY_DELETE_METAFIELD_DEFINITION`` — remove a definition
    (does NOT delete the values themselves).

Friendly create call shape::

    {"namespace":     "shopai",
     "key":           "fraud_score",
     "type":          "number_decimal",
     "name":          "AI Fraud Score",
     "description":   "0.0-1.0 risk score from the brain layer",
     "owner_type":    "ORDER",   # PRODUCT, CUSTOMER, etc.
     "pin":           True}      # surface in admin sidebar

Pattern A: ownerType is required on the *Input shape (not at the
field level — this one's NOT a Pattern A exception). Validations
live as a list of {name, value} dicts.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DEFINITION_FIELDS = """
id
namespace
key
name
description
type {
  name
  category
}
ownerType
pinnedPosition
validations {
  name
  type
  value
}
metafieldsCount
""".strip()


_LIST_DEFINITIONS_QUERY = f"""
query metafieldDefinitions(
  $first: Int!,
  $after: String,
  $ownerType: MetafieldOwnerType!,
  $namespace: String,
  $query: String
) {{
  metafieldDefinitions(
    first: $first,
    after: $after,
    ownerType: $ownerType,
    namespace: $namespace,
    query: $query
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_DEFINITION_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_DEFINITION_MUTATION = f"""
mutation metafieldDefinitionCreate($definition: MetafieldDefinitionInput!) {{
  metafieldDefinitionCreate(definition: $definition) {{
    createdDefinition {{
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


_DELETE_DEFINITION_MUTATION = """
mutation metafieldDefinitionDelete(
  $id: ID!,
  $deleteAllAssociatedMetafields: Boolean
) {
  metafieldDefinitionDelete(
    id: $id,
    deleteAllAssociatedMetafields: $deleteAllAssociatedMetafields
  ) {
    deletedDefinitionId
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

_VALID_OWNER_TYPES = {
    "API_PERMISSION", "ARTICLE", "BLOG", "CARRIER_SERVICE", "COLLECTION",
    "COMPANY", "COMPANY_LOCATION", "CUSTOMER", "DELIVERY_CUSTOMIZATION",
    "DISCOUNT", "DRAFTORDER", "FULFILLMENT_CONSTRAINT_RULE", "GIFT_CARD",
    "LOCATION", "MARKET", "MEDIA_IMAGE", "ORDER", "ORDER_ROUTING_LOCATION_RULE",
    "PAGE", "PAYMENT_CUSTOMIZATION", "PRODUCT", "PRODUCTIMAGE",
    "PRODUCTVARIANT", "SELLING_PLAN", "SHOP", "VALIDATION",
}


class ShopifyMetafieldDefinitionsAdapter(ShopifyBaseAdapter):
    name = "shopify_metafield_definitions"
    capabilities = {
        Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS,
        Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION,
        Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION,
    }
    required_scopes = frozenset({
        "read_metaobject_definitions",
        "write_metaobject_definitions",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        owner_type = params.get("owner_type") or params.get("ownerType")
        if not isinstance(owner_type, str) or owner_type.upper() not in _VALID_OWNER_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'owner_type' is required and must be one of: "
                f"{sorted(_VALID_OWNER_TYPES)}",
            )

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

        variables: dict[str, Any] = {
            "first": limit,
            "after": cursor,
            "ownerType": owner_type.upper(),
        }

        namespace = params.get("namespace")
        if namespace is not None:
            if not isinstance(namespace, str):
                raise AdapterValidationError(
                    self.name, "'namespace' must be a string",
                )
            variables["namespace"] = namespace

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        data = self._gql(_LIST_DEFINITIONS_QUERY, variables)
        envelope = data.get("metafieldDefinitions") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        definitions = [
            self._normalise_definition(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS,
            data={
                "definitions": definitions,
                "count": len(definitions),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        definition_input = self._build_definition_input(params)
        # Pattern A: variable name is "definition" (matches Shopify's
        # convention of naming inputs after the type).
        data = self._gql(_CREATE_DEFINITION_MUTATION, {
            "definition": definition_input,
        })
        self._check_user_errors(data, "metafieldDefinitionCreate")
        payload = data.get("metafieldDefinitionCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION,
            data={
                "definition": self._normalise_definition(
                    payload.get("createdDefinition") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        definition_id = params.get("id") or params.get("definition_id")
        if not isinstance(definition_id, str) or not definition_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the metafield definition) is required",
            )
        delete_values = params.get("delete_all_associated_metafields")
        if delete_values is None:
            delete_values = params.get("deleteAllAssociatedMetafields", False)

        data = self._gql(_DELETE_DEFINITION_MUTATION, {
            "id": definition_id.strip(),
            "deleteAllAssociatedMetafields": bool(delete_values),
        })
        self._check_user_errors(data, "metafieldDefinitionDelete")
        payload = data.get("metafieldDefinitionDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION,
            data={
                "deleted_id": payload.get("deletedDefinitionId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_definition_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        namespace = params.get("namespace")
        if not isinstance(namespace, str) or not namespace.strip():
            raise AdapterValidationError(
                self.name, "'namespace' is required",
            )
        out["namespace"] = namespace.strip()

        key = params.get("key")
        if not isinstance(key, str) or not key.strip():
            raise AdapterValidationError(
                self.name, "'key' is required",
            )
        out["key"] = key.strip()

        mf_type = params.get("type")
        if not isinstance(mf_type, str) or not mf_type.strip():
            raise AdapterValidationError(
                self.name,
                "'type' is required (e.g. 'number_decimal', "
                "'single_line_text_field', 'json')",
            )
        out["type"] = mf_type.strip()

        owner_type = params.get("owner_type") or params.get("ownerType")
        if not isinstance(owner_type, str) or owner_type.upper() not in _VALID_OWNER_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'owner_type' is required and must be one of: "
                f"{sorted(_VALID_OWNER_TYPES)}",
            )
        out["ownerType"] = owner_type.upper()

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise AdapterValidationError(
                    self.name, "'name' must be a string",
                )
            out["name"] = name

        description = params.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    self.name, "'description' must be a string",
                )
            out["description"] = description

        pin = params.get("pin")
        if pin is not None:
            out["pin"] = bool(pin)

        validations = params.get("validations")
        if validations is not None:
            if not isinstance(validations, list):
                raise AdapterValidationError(
                    self.name,
                    "'validations' must be a list of {name, value} dicts",
                )
            out_validations: list[dict[str, str]] = []
            for i, v in enumerate(validations):
                if not isinstance(v, dict):
                    raise AdapterValidationError(
                        self.name, f"validations[{i}] must be a dict",
                    )
                v_name = v.get("name")
                v_value = v.get("value")
                if not isinstance(v_name, str) or not v_name.strip():
                    raise AdapterValidationError(
                        self.name, f"validations[{i}] missing 'name'",
                    )
                if v_value is None:
                    raise AdapterValidationError(
                        self.name, f"validations[{i}] missing 'value'",
                    )
                out_validations.append({
                    "name": v_name,
                    "value": str(v_value),
                })
            out["validations"] = out_validations

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_definition(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        type_node = node.get("type") or {}
        validations_raw = node.get("validations") or []

        # metafieldsCount may be a Count wrapper in 2024-01+ (Pattern D).
        metafields_count_raw = node.get("metafieldsCount", 0)
        if isinstance(metafields_count_raw, dict):
            metafields_count_raw = metafields_count_raw.get("count", 0)
        try:
            metafields_count = int(metafields_count_raw or 0)
        except (TypeError, ValueError):
            metafields_count = 0

        return {
            "id": node.get("id", "") or "",
            "namespace": node.get("namespace", "") or "",
            "key": node.get("key", "") or "",
            "name": node.get("name", "") or "",
            "description": node.get("description", "") or "",
            "type": (
                type_node.get("name", "")
                if isinstance(type_node, dict) else ""
            ) or "",
            "type_category": (
                type_node.get("category", "")
                if isinstance(type_node, dict) else ""
            ) or "",
            "owner_type": node.get("ownerType", "") or "",
            "pinned_position": int(node.get("pinnedPosition") or 0) or 0,
            "is_pinned": node.get("pinnedPosition") is not None,
            "metafields_count": metafields_count,
            "validations": [
                {
                    "name": v.get("name", "") or "",
                    "type": v.get("type", "") or "",
                    "value": v.get("value", "") or "",
                }
                for v in validations_raw if isinstance(v, dict)
            ],
        }
