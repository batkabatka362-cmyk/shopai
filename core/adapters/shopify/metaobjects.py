"""ShopifyMetaobjectsAdapter — typed custom records for the storefront.

Metaobjects are Shopify's "structured custom data" primitive. Where
metafields attach loose key-value pairs to existing Shopify objects
(orders, customers, products), metaobjects let you define your own
*types* — FAQs, testimonials, product highlights, store locations,
AI-generated badge configurations, anything ShopAI's content engines
emit — and query them from the storefront like any other resource.

ShopAI uses metaobjects for two flows:

  * **AI-generated storefront content.** The content engine produces
    FAQs / testimonials / "why-buy" bullets / product comparison
    tables; instead of pushing them as theme HTML, we push them as
    metaobjects and let the theme reference them. That keeps content
    independent of theme code.

  * **Engine state surfaced to the theme.** Things like "current
    winning product" / "today's featured bundle" / "ROAS-tier badge"
    that the theme needs to read at render time. Metaobjects are the
    right primitive — typed, queryable, and visible in admin.

Capabilities (CRUD + list, no definitions):

  * ``SHOPIFY_CREATE_METAOBJECT``  — instantiate a typed record.
  * ``SHOPIFY_UPDATE_METAOBJECT``  — change fields on an existing one.
  * ``SHOPIFY_GET_METAOBJECT``     — fetch by id OR by (type, handle).
  * ``SHOPIFY_LIST_METAOBJECTS``   — page through one type.

Definition CRUD (``metaobjectDefinitionCreate`` etc.) is intentionally
NOT in this pass. Definitions are one-time schema setup that engines
rarely change at runtime; the merchant or a migration creates them.
We can add a separate adapter when an engine actually needs to spin
up definitions on the fly.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Common selection set so create / update / get all return the same
# shape and the normaliser only has to know one structure.
_METAOBJECT_NODE_FIELDS = """
id
handle
type
displayName
updatedAt
fields {
  key
  value
  type
}
""".strip()


_CREATE_METAOBJECT_MUTATION = f"""
mutation metaobjectCreate($metaobject: MetaobjectCreateInput!) {{
  metaobjectCreate(metaobject: $metaobject) {{
    metaobject {{
      {_METAOBJECT_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_METAOBJECT_MUTATION = f"""
mutation metaobjectUpdate($id: ID!, $metaobject: MetaobjectUpdateInput!) {{
  metaobjectUpdate(id: $id, metaobject: $metaobject) {{
    metaobject {{
      {_METAOBJECT_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_GET_METAOBJECT_BY_ID_QUERY = f"""
query getMetaobject($id: ID!) {{
  metaobject(id: $id) {{
    {_METAOBJECT_NODE_FIELDS}
  }}
}}
""".strip()


_GET_METAOBJECT_BY_HANDLE_QUERY = f"""
query getMetaobjectByHandle($handle: MetaobjectHandleInput!) {{
  metaobjectByHandle(handle: $handle) {{
    {_METAOBJECT_NODE_FIELDS}
  }}
}}
""".strip()


_LIST_METAOBJECTS_QUERY = f"""
query metaobjects($type: String!, $first: Int!, $after: String) {{
  metaobjects(type: $type, first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_METAOBJECT_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyMetaobjectsAdapter(ShopifyBaseAdapter):
    name = "shopify_metaobjects"
    capabilities = {
        Capability.SHOPIFY_CREATE_METAOBJECT,
        Capability.SHOPIFY_UPDATE_METAOBJECT,
        Capability.SHOPIFY_GET_METAOBJECT,
        Capability.SHOPIFY_LIST_METAOBJECTS,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_METAOBJECT:
            return self._create_metaobject(params)
        if capability == Capability.SHOPIFY_UPDATE_METAOBJECT:
            return self._update_metaobject(params)
        if capability == Capability.SHOPIFY_GET_METAOBJECT:
            return self._get_metaobject(params)
        if capability == Capability.SHOPIFY_LIST_METAOBJECTS:
            return self._list_metaobjects(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create_metaobject(self, params: dict[str, Any]) -> Any:
        metaobject_input = self._build_create_input(params)
        data = self._gql(
            _CREATE_METAOBJECT_MUTATION,
            {"metaobject": metaobject_input},
        )
        self._check_user_errors(data, "metaobjectCreate")
        payload = data.get("metaobjectCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_METAOBJECT,
            data={"metaobject": self._normalise_metaobject(
                payload.get("metaobject") or {}
            )},
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``MetaobjectCreateInput``.

        Friendly form::

            {
              "type": "faq",                              # required
              "handle": "shipping-faq",                   # optional, auto if missing
              "fields": {
                  "question": "When does it ship?",       # snake_case
                  "answer":   "Within 24h.",              # values are coerced to strings
                  "priority": 5,
              },
            }

        OR with explicit field types::

            {
              "type": "faq",
              "fields": [
                {"key": "question", "value": "..."},
                {"key": "answer",   "value": "...", "type": "rich_text_field"},
              ],
            }
        """
        obj_type = params.get("type")
        if not isinstance(obj_type, str) or not obj_type.strip():
            raise AdapterValidationError(
                "shopify_metaobjects",
                "'type' is required (e.g. 'faq' or '$app:faq')",
            )

        out: dict[str, Any] = {"type": obj_type.strip()}

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str):
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    "'handle' must be a string",
                )
            out["handle"] = handle.strip()

        fields = _normalise_fields(params.get("fields"), where="create")
        if not fields:
            raise AdapterValidationError(
                "shopify_metaobjects",
                "'fields' is required (dict or list of key/value pairs)",
            )
        out["fields"] = fields

        return out

    # ── Update ─────────────────────────────────────────────────────

    def _update_metaobject(self, params: dict[str, Any]) -> Any:
        obj_id = params.get("id") or params.get("metaobject_id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            raise AdapterValidationError(
                "shopify_metaobjects",
                "'id' (Shopify GID for the metaobject) is required",
            )

        update_input: dict[str, Any] = {}
        if "handle" in params:
            handle = params["handle"]
            if not isinstance(handle, str):
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    "'handle' must be a string",
                )
            update_input["handle"] = handle.strip()

        if "fields" in params:
            update_input["fields"] = _normalise_fields(
                params["fields"], where="update",
            )

        if not update_input:
            raise AdapterValidationError(
                "shopify_metaobjects",
                "update needs at least one field besides 'id' "
                "(handle or fields)",
            )

        data = self._gql(_UPDATE_METAOBJECT_MUTATION, {
            "id": obj_id.strip(),
            "metaobject": update_input,
        })
        self._check_user_errors(data, "metaobjectUpdate")
        payload = data.get("metaobjectUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_METAOBJECT,
            data={"metaobject": self._normalise_metaobject(
                payload.get("metaobject") or {}
            )},
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get_metaobject(self, params: dict[str, Any]) -> Any:
        """Fetch by id (preferred) or (type, handle).

        Two paths because the engine often only knows the human handle
        ("today-featured-bundle"), not the GID. The adapter dispatches
        to whichever query Shopify exposes for the input shape.
        """
        obj_id = params.get("id") or params.get("metaobject_id")
        handle = params.get("handle")
        obj_type = params.get("type")

        if obj_id:
            if not isinstance(obj_id, str):
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    "'id' must be a string",
                )
            data = self._gql(_GET_METAOBJECT_BY_ID_QUERY, {
                "id": obj_id.strip(),
            })
            node = data.get("metaobject")
        elif handle and obj_type:
            if not isinstance(handle, str) or not isinstance(obj_type, str):
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    "'handle' and 'type' must both be strings",
                )
            data = self._gql(_GET_METAOBJECT_BY_HANDLE_QUERY, {
                "handle": {"handle": handle.strip(), "type": obj_type.strip()},
            })
            node = data.get("metaobjectByHandle")
        else:
            raise AdapterValidationError(
                "shopify_metaobjects",
                "get needs either 'id' OR ('type' AND 'handle')",
            )

        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_METAOBJECT,
                data={"metaobject": None, "found": False},
            )
        return self._success(
            Capability.SHOPIFY_GET_METAOBJECT,
            data={
                "metaobject": self._normalise_metaobject(node),
                "found": True,
            },
        )

    # ── List ───────────────────────────────────────────────────────

    def _list_metaobjects(self, params: dict[str, Any]) -> Any:
        obj_type = params.get("type")
        if not isinstance(obj_type, str) or not obj_type.strip():
            raise AdapterValidationError(
                "shopify_metaobjects",
                "'type' is required (the metaobject type to page)",
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
                "shopify_metaobjects",
                "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_METAOBJECTS_QUERY, {
            "type": obj_type.strip(),
            "first": limit,
            "after": cursor,
        })
        envelope = data.get("metaobjects") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        metaobjects = [
            self._normalise_metaobject(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_METAOBJECTS,
            data={
                "metaobjects": metaobjects,
                "count": len(metaobjects),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_metaobject(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        fields_list = node.get("fields") or []
        # Flatten the field array into a dict so callers can do
        # m["fields"]["question"] instead of scanning a list. Field
        # order is preserved via the parallel _field_meta map.
        fields_flat: dict[str, str] = {}
        field_meta: dict[str, dict[str, str]] = {}
        if isinstance(fields_list, list):
            for f in fields_list:
                if not isinstance(f, dict):
                    continue
                key = f.get("key")
                if not isinstance(key, str):
                    continue
                value = f.get("value")
                fields_flat[key] = value if value is not None else ""
                field_meta[key] = {
                    "type": f.get("type", "") or "",
                }
        return {
            "id": node.get("id", "") or "",
            "handle": node.get("handle", "") or "",
            "type": node.get("type", "") or "",
            "display_name": node.get("displayName", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "fields": fields_flat,
            "field_meta": field_meta,
        }


def _normalise_fields(raw: Any, *, where: str) -> list[dict[str, Any]]:
    """Convert ShopAI-friendly field shapes into ``MetaobjectFieldInput``.

    Accepts:

      * dict   — ``{"question": "Q", "answer": "A"}``
                 (most common; values coerced to strings)
      * list   — ``[{"key": "question", "value": "Q"}, ...]``
                 (when the caller cares about ordering / explicit types)

    Raises AdapterValidationError on unsupported shapes so callers
    fail fast instead of paying for a userErrors round-trip.
    """
    if raw is None:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            if not isinstance(k, str) or not k.strip():
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    f"{where}: field keys must be non-empty strings",
                )
            # Shopify field values are typed strings — coerce primitives
            # so callers can pass `5` or `True` directly.
            if v is None:
                str_value = ""
            elif isinstance(v, bool):
                str_value = "true" if v else "false"
            elif isinstance(v, (int, float, str)):
                str_value = str(v)
            else:
                # dicts/lists serialised as JSON string so the merchant
                # can store rich content without round-tripping.
                import json as _json
                try:
                    str_value = _json.dumps(v)
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        "shopify_metaobjects",
                        f"{where}: field {k!r} value not JSON-serialisable",
                    ) from exc
            out.append({"key": k, "value": str_value})
        return out

    if isinstance(raw, list):
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    f"{where}: fields[{i}] must be a dict",
                )
            key = entry.get("key")
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    "shopify_metaobjects",
                    f"{where}: fields[{i}] missing 'key'",
                )
            value = entry.get("value")
            if value is None:
                value_str = ""
            elif isinstance(value, str):
                value_str = value
            else:
                # Same primitive coercion as the dict branch.
                if isinstance(value, bool):
                    value_str = "true" if value else "false"
                elif isinstance(value, (int, float)):
                    value_str = str(value)
                else:
                    import json as _json
                    try:
                        value_str = _json.dumps(value)
                    except (TypeError, ValueError) as exc:
                        raise AdapterValidationError(
                            "shopify_metaobjects",
                            f"{where}: fields[{i}] value not JSON-serialisable",
                        ) from exc
            field_input: dict[str, Any] = {"key": key, "value": value_str}
            # Explicit type is allowed but optional — Shopify infers
            # from the metaobject definition when it's omitted.
            ftype = entry.get("type")
            if ftype is not None:
                if not isinstance(ftype, str):
                    raise AdapterValidationError(
                        "shopify_metaobjects",
                        f"{where}: fields[{i}] 'type' must be a string",
                    )
                # Note: MetaobjectFieldInput on Shopify doesn't
                # actually accept a `type` field on input — type is
                # determined by the definition. We accept it from the
                # caller for documentation but drop it on the wire.
                _ = ftype
            out.append(field_input)
        return out

    raise AdapterValidationError(
        "shopify_metaobjects",
        f"{where}: 'fields' must be a dict or list, got {type(raw).__name__}",
    )
