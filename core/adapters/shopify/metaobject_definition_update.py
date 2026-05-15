"""ShopifyMetaobjectDefinitionUpdateAdapter — schema migration.

Companion to ``metaobject_definitions.py``, which covers the LIST /
GET / CREATE / DELETE corners. Updating an existing definition has
its own surface area large enough to warrant a dedicated adapter:
field add / rename / mark-required / drop, capability toggle
(publishable / translatable / renderable / online-store), access
re-scope, display-name-key flip, and field-order reset.

This is the schema-migration tool ShopAI's content engine uses
when the storefront's data model evolves — adding a "nutrition_facts"
field to an existing "Recipe" type, renaming an old field without
losing its values, or making a previously-optional field required
once enough merchants have populated it.

Capability:

  * ``SHOPIFY_UPDATE_METAOBJECT_DEFINITION`` —
    metaobjectDefinitionUpdate. Pattern A: id at field level,
    update body inside ``definition``.

Friendly call shape::

    {"id": "gid://shopify/MetaobjectDefinition/123",
     "name": "Recipe v2",                      # optional rename
     "description": "Updated description",     # optional
     "display_name_key": "title",              # optional
     "reset_field_order": True,                # optional
     "field_creates": [
       {"key": "nutrition", "type": "json",
        "name": "Nutrition facts", "required": False},
     ],
     "field_updates": [
       {"key": "title", "name": "Recipe title",
        "required": True},
     ],
     "field_deletes": ["legacy_summary"],      # keys to drop
     "access": {"admin": "MERCHANT_READ_WRITE",
                "storefront": "PUBLIC_READ"},
     "capabilities": {
       "publishable": {"enabled": True},
       "translatable": {"enabled": True},
     }}

The adapter packages each of ``field_creates`` / ``field_updates``
/ ``field_deletes`` into the operations-list shape Shopify expects
(``MetaobjectFieldDefinitionOperationInput`` with one of
``create``/``update``/``delete``). At least ONE of the update
fields must be present — sending an empty definition is rejected
client-side rather than burning a GraphQL hop.

Pattern F: ``MetaobjectUserError`` (the mutation's error type) HAS
the ``code`` field — keep it in the selection.

Pattern E note: gated by ``write_metaobject_definitions`` scope.
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
}
access {
  admin
  storefront
}
capabilities {
  publishable { enabled }
  translatable { enabled }
  renderable { enabled }
  onlineStore { enabled }
}
""".strip()


_UPDATE_MUTATION = f"""
mutation metaobjectDefinitionUpdate(
  $id: ID!,
  $definition: MetaobjectDefinitionUpdateInput!
) {{
  metaobjectDefinitionUpdate(id: $id, definition: $definition) {{
    metaobjectDefinition {{
      {_DEFINITION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
      elementIndex
      elementKey
    }}
  }}
}}
""".strip()


# Per Shopify, validation values are JSON-encoded strings, but the
# friendly call shape lets engines pass dicts/lists/numbers/bools and
# we coerce here.
import json as _json


_VALID_ADMIN_ACCESS = {
    "PUBLIC_READ_WRITE",
    "MERCHANT_READ",
    "MERCHANT_READ_WRITE",
}
_VALID_STOREFRONT_ACCESS = {
    "NONE",
    "PUBLIC_READ",
}


class ShopifyMetaobjectDefinitionUpdateAdapter(ShopifyBaseAdapter):
    name = "shopify_metaobject_definition_update"
    capabilities = {
        Capability.SHOPIFY_UPDATE_METAOBJECT_DEFINITION,
    }
    required_scopes = frozenset({"write_metaobject_definitions"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_METAOBJECT_DEFINITION:
            return self._update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _update(self, params: dict[str, Any]) -> Any:
        definition_id = (
            params.get("id")
            or params.get("definition_id")
            or params.get("metaobjectDefinitionId")
        )
        if not isinstance(definition_id, str) or not definition_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the metaobject definition) "
                "is required",
            )

        definition = self._build_definition(params)
        if not definition:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: name, description, "
                "display_name_key, reset_field_order, field_creates, "
                "field_updates, field_deletes, access, capabilities",
            )

        data = self._gql(_UPDATE_MUTATION, {
            "id": definition_id.strip(),
            "definition": definition,
        })
        self._check_user_errors(data, "metaobjectDefinitionUpdate")
        payload = data.get("metaobjectDefinitionUpdate") or {}
        node = payload.get("metaobjectDefinition") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_METAOBJECT_DEFINITION,
            data={
                "metaobject_definition": self._normalise(node),
            },
        )

    # ── Builders ──────────────────────────────────────────────────

    def _build_definition(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        name = params.get("name")
        if isinstance(name, str) and name.strip():
            out["name"] = name.strip()

        description = params.get("description")
        if isinstance(description, str):
            out["description"] = description

        display_name_key = (
            params.get("display_name_key")
            or params.get("displayNameKey")
        )
        if isinstance(display_name_key, str) and display_name_key.strip():
            out["displayNameKey"] = display_name_key.strip()

        reset_field_order = (
            params.get("reset_field_order")
            if "reset_field_order" in params
            else params.get("resetFieldOrder")
        )
        if reset_field_order is not None:
            out["resetFieldOrder"] = bool(reset_field_order)

        operations = self._build_field_operations(params)
        if operations:
            out["fieldDefinitions"] = operations

        access = self._build_access(params.get("access"))
        if access:
            out["access"] = access

        capabilities = self._build_capabilities(params.get("capabilities"))
        if capabilities:
            out["capabilities"] = capabilities

        return out

    def _build_field_operations(
        self, params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ops: list[dict[str, Any]] = []

        creates = params.get("field_creates") or []
        if not isinstance(creates, list):
            raise AdapterValidationError(
                self.name, "'field_creates' must be a list",
            )
        for i, raw in enumerate(creates):
            if not isinstance(raw, dict):
                raise AdapterValidationError(
                    self.name, f"field_creates[{i}] must be a dict",
                )
            key = raw.get("key")
            type_ = raw.get("type")
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    self.name, f"field_creates[{i}].key is required",
                )
            if not isinstance(type_, str) or not type_.strip():
                raise AdapterValidationError(
                    self.name,
                    f"field_creates[{i}].type is required (e.g. "
                    "'single_line_text_field', 'json', "
                    "'list.metaobject_reference')",
                )
            create: dict[str, Any] = {
                "key": key.strip(), "type": type_.strip(),
            }
            self._copy_field_optionals(raw, create)
            ops.append({"create": create})

        updates = params.get("field_updates") or []
        if not isinstance(updates, list):
            raise AdapterValidationError(
                self.name, "'field_updates' must be a list",
            )
        for i, raw in enumerate(updates):
            if not isinstance(raw, dict):
                raise AdapterValidationError(
                    self.name, f"field_updates[{i}] must be a dict",
                )
            key = raw.get("key")
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    self.name, f"field_updates[{i}].key is required",
                )
            update: dict[str, Any] = {"key": key.strip()}
            self._copy_field_optionals(raw, update)
            ops.append({"update": update})

        deletes = params.get("field_deletes") or []
        if isinstance(deletes, str):
            deletes = [deletes]
        if not isinstance(deletes, list):
            raise AdapterValidationError(
                self.name,
                "'field_deletes' must be a list of keys (strings)",
            )
        for i, raw in enumerate(deletes):
            if not isinstance(raw, str) or not raw.strip():
                raise AdapterValidationError(
                    self.name,
                    f"field_deletes[{i}] must be a non-empty key",
                )
            ops.append({"delete": {"key": raw.strip()}})

        return ops

    @staticmethod
    def _copy_field_optionals(
        raw: dict[str, Any], dst: dict[str, Any],
    ) -> None:
        if isinstance(raw.get("name"), str):
            dst["name"] = raw["name"]
        if isinstance(raw.get("description"), str):
            dst["description"] = raw["description"]
        if "required" in raw:
            dst["required"] = bool(raw["required"])
        validations = raw.get("validations")
        if isinstance(validations, list):
            normalised: list[dict[str, str]] = []
            for v in validations:
                if not isinstance(v, dict):
                    continue
                name = v.get("name")
                value = v.get("value")
                if not isinstance(name, str) or not name.strip():
                    continue
                if isinstance(value, (dict, list, bool, int, float)):
                    value = _json.dumps(value)
                elif value is None:
                    value = ""
                else:
                    value = str(value)
                normalised.append(
                    {"name": name.strip(), "value": value},
                )
            if normalised:
                dst["validations"] = normalised

    def _build_access(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'access' must be a dict {admin?, storefront?}",
            )
        out: dict[str, Any] = {}
        admin = raw.get("admin")
        if admin is not None:
            if not isinstance(admin, str):
                raise AdapterValidationError(
                    self.name, "'access.admin' must be a string",
                )
            up = admin.strip().upper()
            if up not in _VALID_ADMIN_ACCESS:
                raise AdapterValidationError(
                    self.name,
                    f"'access.admin' must be one of "
                    f"{sorted(_VALID_ADMIN_ACCESS)}",
                )
            out["admin"] = up
        storefront = raw.get("storefront")
        if storefront is not None:
            if not isinstance(storefront, str):
                raise AdapterValidationError(
                    self.name, "'access.storefront' must be a string",
                )
            up = storefront.strip().upper()
            if up not in _VALID_STOREFRONT_ACCESS:
                raise AdapterValidationError(
                    self.name,
                    f"'access.storefront' must be one of "
                    f"{sorted(_VALID_STOREFRONT_ACCESS)}",
                )
            out["storefront"] = up
        return out or None

    def _build_capabilities(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'capabilities' must be a dict of capability flags",
            )
        out: dict[str, Any] = {}
        for cap_name in (
            "publishable", "translatable", "renderable", "onlineStore",
        ):
            # Accept both snake_case and camelCase.
            snake = {
                "publishable": "publishable",
                "translatable": "translatable",
                "renderable": "renderable",
                "onlineStore": "online_store",
            }[cap_name]
            block = raw.get(cap_name)
            if block is None:
                block = raw.get(snake)
            if block is None:
                continue
            if not isinstance(block, dict):
                raise AdapterValidationError(
                    self.name,
                    f"'capabilities.{cap_name}' must be a dict",
                )
            if "enabled" not in block:
                raise AdapterValidationError(
                    self.name,
                    f"'capabilities.{cap_name}.enabled' is required",
                )
            cap_out: dict[str, Any] = {"enabled": bool(block["enabled"])}
            data = block.get("data")
            if isinstance(data, dict) and data:
                cap_out["data"] = data
            out[cap_name] = cap_out
        return out or None

    # ── Normalisation ─────────────────────────────────────────────

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        access = node.get("access") or {}
        capabilities = node.get("capabilities") or {}
        fields_raw = node.get("fieldDefinitions") or []
        fields = []
        for f in fields_raw:
            if not isinstance(f, dict):
                continue
            type_ = f.get("type") or {}
            fields.append({
                "key": f.get("key", "") or "",
                "name": f.get("name", "") or "",
                "description": f.get("description", "") or "",
                "required": bool(f.get("required", False)),
                "type_name": (
                    type_.get("name", "")
                    if isinstance(type_, dict) else ""
                ) or "",
                "type_category": (
                    type_.get("category", "")
                    if isinstance(type_, dict) else ""
                ) or "",
            })

        def _enabled(key: str) -> bool:
            block = capabilities.get(key) or {}
            return bool(
                block.get("enabled", False)
                if isinstance(block, dict) else False
            )

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "type": node.get("type", "") or "",
            "description": node.get("description", "") or "",
            "display_name_key": node.get("displayNameKey", "") or "",
            "field_definitions": fields,
            "access_admin": (
                access.get("admin", "")
                if isinstance(access, dict) else ""
            ) or "",
            "access_storefront": (
                access.get("storefront", "")
                if isinstance(access, dict) else ""
            ) or "",
            "capability_publishable": _enabled("publishable"),
            "capability_translatable": _enabled("translatable"),
            "capability_renderable": _enabled("renderable"),
            "capability_online_store": _enabled("onlineStore"),
        }
