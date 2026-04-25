"""ShopifyMetaobjectDefinitionsAdapter — metaobject schema management.

Companion to ``metaobjects.py`` (which writes metaobject INSTANCES).
Metaobject definitions are the SCHEMA: declare a "Recipe" or
"Testimonial" or "Brand Story" type with named fields, validations,
and admin-UI flags. Without a definition, you can't create instances.

ShopAI's content + creative engines use these to:

  * Register custom storefront content types ("Style Guide",
    "Promo Banner", "Featured Recipe") that the merchant theme
    can render via the Liquid metaobject helper.
  * Migrate freeform metafield blobs into typed multi-field
    metaobjects with admin UI.
  * Support multi-instance custom data (one Recipe per product
    rather than one big metafield with all recipes serialized).

Capabilities:

  * ``SHOPIFY_LIST_METAOBJECT_DEFINITIONS``  — paginated list.
  * ``SHOPIFY_GET_METAOBJECT_DEFINITION``    — single definition with
    full field schema.
  * ``SHOPIFY_CREATE_METAOBJECT_DEFINITION`` — register a new type.
  * ``SHOPIFY_DELETE_METAOBJECT_DEFINITION`` — remove a definition
    (deletes ALL instances — destructive, hence the explicit flag).

Friendly create call shape::

    {"name":         "Recipe",
     "type":         "recipe",   # storefront-side handle
     "description":  "Cookable recipes attached to products",
     "field_definitions": [
       {"key": "title", "name": "Title",
        "type": "single_line_text_field",
        "required": True},
       {"key": "ingredients", "name": "Ingredients",
        "type": "list.single_line_text_field"},
       {"key": "cook_time_minutes", "name": "Cook time (min)",
        "type": "number_integer"},
     ]}

Pattern A: variable name is "definition" (matches
MetaobjectDefinitionCreateInput) — same convention as the
metafield_definitions adapter.

Pattern E note: gated by ``read_metaobject_definitions`` /
``write_metaobject_definitions`` scopes.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_METAOBJECT_DEFINITION_FIELDS = """
id
name
type
description
displayNameKey
fieldDefinitions {
  key
  name
  description
  required
  type {
    name
    category
  }
  validations {
    name
    type
    value
  }
}
metaobjectsCount
""".strip()


_LIST_DEFINITIONS_QUERY = f"""
query metaobjectDefinitions($first: Int!, $after: String) {{
  metaobjectDefinitions(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_METAOBJECT_DEFINITION_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_DEFINITION_QUERY = f"""
query metaobjectDefinition($id: ID!) {{
  metaobjectDefinition(id: $id) {{
    {_METAOBJECT_DEFINITION_FIELDS}
  }}
}}
""".strip()


_CREATE_DEFINITION_MUTATION = f"""
mutation metaobjectDefinitionCreate(
  $definition: MetaobjectDefinitionCreateInput!
) {{
  metaobjectDefinitionCreate(definition: $definition) {{
    metaobjectDefinition {{
      {_METAOBJECT_DEFINITION_FIELDS}
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
mutation metaobjectDefinitionDelete($id: ID!) {
  metaobjectDefinitionDelete(id: $id) {
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


class ShopifyMetaobjectDefinitionsAdapter(ShopifyBaseAdapter):
    name = "shopify_metaobject_definitions"
    capabilities = {
        Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS,
        Capability.SHOPIFY_GET_METAOBJECT_DEFINITION,
        Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION,
        Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_METAOBJECT_DEFINITION:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
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
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_DEFINITIONS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("metaobjectDefinitions") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        definitions = [
            self._normalise_definition(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS,
            data={
                "definitions": definitions,
                "count": len(definitions),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        definition_id = params.get("id") or params.get("definition_id")
        if not isinstance(definition_id, str) or not definition_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the metaobject definition) is required",
            )
        data = self._gql(_GET_DEFINITION_QUERY, {
            "id": definition_id.strip(),
        })
        node = data.get("metaobjectDefinition") or {}
        return self._success(
            Capability.SHOPIFY_GET_METAOBJECT_DEFINITION,
            data={
                "definition": self._normalise_definition(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        definition_input = self._build_create_input(params)
        data = self._gql(_CREATE_DEFINITION_MUTATION, {
            "definition": definition_input,
        })
        self._check_user_errors(data, "metaobjectDefinitionCreate")
        payload = data.get("metaobjectDefinitionCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION,
            data={
                "definition": self._normalise_definition(
                    payload.get("metaobjectDefinition") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        definition_id = params.get("id") or params.get("definition_id")
        if not isinstance(definition_id, str) or not definition_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the metaobject definition) is required",
            )
        data = self._gql(_DELETE_DEFINITION_MUTATION, {
            "id": definition_id.strip(),
        })
        self._check_user_errors(data, "metaobjectDefinitionDelete")
        payload = data.get("metaobjectDefinitionDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_create_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        type_handle = params.get("type")
        if not isinstance(type_handle, str) or not type_handle.strip():
            raise AdapterValidationError(
                self.name,
                "'type' is required (lowercase storefront handle, "
                "e.g. 'recipe', 'testimonial')",
            )
        out["type"] = type_handle.strip()

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise AdapterValidationError(
                    self.name, "'name' must be a string",
                )
            out["name"] = name.strip()

        description = params.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    self.name, "'description' must be a string",
                )
            out["description"] = description

        display_name_key = params.get("display_name_key") or params.get(
            "displayNameKey"
        )
        if display_name_key is not None:
            if not isinstance(display_name_key, str):
                raise AdapterValidationError(
                    self.name, "'display_name_key' must be a string",
                )
            out["displayNameKey"] = display_name_key

        field_defs = params.get("field_definitions") or params.get(
            "fieldDefinitions"
        )
        if not isinstance(field_defs, list) or not field_defs:
            raise AdapterValidationError(
                self.name,
                "'field_definitions' must be a non-empty list of "
                "{key, name, type, ...} dicts",
            )
        out["fieldDefinitions"] = [
            self._build_field_definition(fd, i)
            for i, fd in enumerate(field_defs)
        ]

        return out

    def _build_field_definition(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"field_definitions[{index}] must be a dict",
            )
        key = raw.get("key")
        if not isinstance(key, str) or not key.strip():
            raise AdapterValidationError(
                self.name,
                f"field_definitions[{index}] missing 'key'",
            )
        type_handle = raw.get("type")
        if not isinstance(type_handle, str) or not type_handle.strip():
            raise AdapterValidationError(
                self.name,
                f"field_definitions[{index}] missing 'type'",
            )

        out: dict[str, Any] = {
            "key": key.strip(),
            "type": type_handle.strip(),
        }

        name = raw.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise AdapterValidationError(
                    self.name,
                    f"field_definitions[{index}].name must be a string",
                )
            out["name"] = name

        description = raw.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    self.name,
                    f"field_definitions[{index}].description must be a string",
                )
            out["description"] = description

        required = raw.get("required")
        if required is not None:
            out["required"] = bool(required)

        validations = raw.get("validations")
        if validations is not None:
            if not isinstance(validations, list):
                raise AdapterValidationError(
                    self.name,
                    f"field_definitions[{index}].validations must be a list",
                )
            out_validations: list[dict[str, str]] = []
            for j, v in enumerate(validations):
                if not isinstance(v, dict):
                    raise AdapterValidationError(
                        self.name,
                        f"field_definitions[{index}].validations[{j}] "
                        "must be a dict",
                    )
                v_name = v.get("name")
                v_value = v.get("value")
                if not isinstance(v_name, str) or not v_name.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"field_definitions[{index}].validations[{j}] "
                        "missing 'name'",
                    )
                if v_value is None:
                    raise AdapterValidationError(
                        self.name,
                        f"field_definitions[{index}].validations[{j}] "
                        "missing 'value'",
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
        field_defs_raw = node.get("fieldDefinitions") or []
        field_defs = []
        for fd in field_defs_raw:
            if not isinstance(fd, dict):
                continue
            type_node = fd.get("type") or {}
            validations_raw = fd.get("validations") or []
            field_defs.append({
                "key": fd.get("key", "") or "",
                "name": fd.get("name", "") or "",
                "description": fd.get("description", "") or "",
                "required": bool(fd.get("required", False)),
                "type": (
                    type_node.get("name", "")
                    if isinstance(type_node, dict) else ""
                ) or "",
                "type_category": (
                    type_node.get("category", "")
                    if isinstance(type_node, dict) else ""
                ) or "",
                "validations": [
                    {
                        "name": v.get("name", "") or "",
                        "type": v.get("type", "") or "",
                        "value": v.get("value", "") or "",
                    }
                    for v in validations_raw if isinstance(v, dict)
                ],
            })

        # metaobjectsCount may be Count wrapper (Pattern D).
        count_raw = node.get("metaobjectsCount", 0)
        if isinstance(count_raw, dict):
            count_raw = count_raw.get("count", 0)
        try:
            metaobjects_count = int(count_raw or 0)
        except (TypeError, ValueError):
            metaobjects_count = 0

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "type": node.get("type", "") or "",
            "description": node.get("description", "") or "",
            "display_name_key": node.get("displayNameKey", "") or "",
            "field_definitions": field_defs,
            "metaobjects_count": metaobjects_count,
        }
