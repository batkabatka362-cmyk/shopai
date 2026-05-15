"""ShopifyMetaobjectsUpsertAdapter — atomic upsert + bulk delete.

Companion to ``metaobjects.py`` (which CRUDs metaobject INSTANCES
one at a time) and ``metaobject_definitions.py`` (which manages the
SCHEMAS). The upsert + bulk-delete path is what engines reach for
when migrating data INTO a metaobject type at scale.

ShopAI's content + creative engines use these to:

  * Idempotently sync recipes / testimonials / brand-stories from
    a CMS into Shopify metaobjects without first checking whether
    the record exists (upsert handles both create + update).
  * Bulk-purge stale metaobjects when a content set is deprecated
    (kill the entire "old promo" type without paginating through
    metaobjects.py one-at-a-time).

Capabilities:

  * ``SHOPIFY_UPSERT_METAOBJECT``        — create-or-update an
    instance keyed by handle. Atomic with respect to handle
    uniqueness (no race between read + create).
  * ``SHOPIFY_BULK_DELETE_METAOBJECTS``  — delete multiple instances
    in a single call (up to Shopify's bulk limit; engines chunk
    larger sets).

Friendly call shape::

    upsert::
      {"type":   "recipe",
       "handle": "chocolate-chip-cookies",
       "fields": [
         {"key": "title", "value": "Chocolate Chip Cookies"},
         {"key": "cook_time_minutes", "value": "12"},
       ]}

    bulk_delete::
      {"ids": ["gid://shopify/Metaobject/1",
               "gid://shopify/Metaobject/2"]}

Pattern A: ``metaobjectUpsert`` takes the handle/type lookup at
field level + a ``MetaobjectUpsertInput`` for the fields. Same
convention as metafield_definitions / validations.

Pattern E note: gated by ``write_metaobjects`` scope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_METAOBJECT_FIELDS = """
id
type
handle
displayName
updatedAt
fields {
  key
  value
  type
}
""".strip()


_UPSERT_METAOBJECT_MUTATION = f"""
mutation metaobjectUpsert(
  $handle: MetaobjectHandleInput!,
  $metaobject: MetaobjectUpsertInput!
) {{
  metaobjectUpsert(handle: $handle, metaobject: $metaobject) {{
    metaobject {{
      {_METAOBJECT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_BULK_DELETE_METAOBJECTS_MUTATION = """
mutation metaobjectBulkDelete($where: MetaobjectBulkDeleteWhereCondition!) {
  metaobjectBulkDelete(where: $where) {
    job {
      id
      done
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyMetaobjectsUpsertAdapter(ShopifyBaseAdapter):
    name = "shopify_metaobjects_upsert"
    capabilities = {
        Capability.SHOPIFY_UPSERT_METAOBJECT,
        Capability.SHOPIFY_BULK_DELETE_METAOBJECTS,
    }
    required_scopes = frozenset({"write_metaobjects"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPSERT_METAOBJECT:
            return self._upsert(params)
        if capability == Capability.SHOPIFY_BULK_DELETE_METAOBJECTS:
            return self._bulk_delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Upsert ─────────────────────────────────────────────────────

    def _upsert(self, params: dict[str, Any]) -> Any:
        type_handle = params.get("type")
        if not isinstance(type_handle, str) or not type_handle.strip():
            raise AdapterValidationError(
                self.name,
                "'type' is required (the metaobject definition's type "
                "handle, e.g. 'recipe')",
            )
        handle = params.get("handle")
        if not isinstance(handle, str) or not handle.strip():
            raise AdapterValidationError(
                self.name,
                "'handle' is required (the per-instance unique slug)",
            )

        fields_raw = params.get("fields")
        if not isinstance(fields_raw, list) or not fields_raw:
            raise AdapterValidationError(
                self.name,
                "'fields' must be a non-empty list of {key, value} dicts",
            )
        fields_input: list[dict[str, str]] = []
        for i, f in enumerate(fields_raw):
            if not isinstance(f, dict):
                raise AdapterValidationError(
                    self.name, f"fields[{i}] must be a dict",
                )
            key = f.get("key")
            value = f.get("value")
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    self.name, f"fields[{i}] missing 'key'",
                )
            if value is None:
                raise AdapterValidationError(
                    self.name, f"fields[{i}] missing 'value'",
                )
            fields_input.append({
                "key": key.strip(),
                # Shopify always wants the value as a string per
                # metafield convention.
                "value": str(value) if not isinstance(value, str) else value,
            })

        metaobject_input: dict[str, Any] = {"fields": fields_input}

        capabilities = params.get("capabilities")
        if capabilities is not None:
            if not isinstance(capabilities, dict):
                raise AdapterValidationError(
                    self.name, "'capabilities' must be a dict",
                )
            metaobject_input["capabilities"] = capabilities

        data = self._gql(_UPSERT_METAOBJECT_MUTATION, {
            "handle": {
                "type": type_handle.strip(),
                "handle": handle.strip(),
            },
            "metaobject": metaobject_input,
        })
        self._check_user_errors(data, "metaobjectUpsert")
        payload = data.get("metaobjectUpsert") or {}
        return self._success(
            Capability.SHOPIFY_UPSERT_METAOBJECT,
            data={
                "metaobject": self._normalise_metaobject(
                    payload.get("metaobject") or {},
                ),
            },
        )

    # ── Bulk delete ───────────────────────────────────────────────

    def _bulk_delete(self, params: dict[str, Any]) -> Any:
        ids_raw = params.get("ids") or params.get("metaobject_ids")
        if isinstance(ids_raw, str):
            ids_raw = [ids_raw]
        if not isinstance(ids_raw, list) or not ids_raw or not all(
            isinstance(x, str) for x in ids_raw
        ):
            raise AdapterValidationError(
                self.name,
                "'ids' must be a non-empty list of metaobject GIDs",
            )
        ids = [x.strip() for x in ids_raw if x.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'ids' contained only blanks",
            )

        data = self._gql(_BULK_DELETE_METAOBJECTS_MUTATION, {
            "where": {"ids": ids},
        })
        self._check_user_errors(data, "metaobjectBulkDelete")
        payload = data.get("metaobjectBulkDelete") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_BULK_DELETE_METAOBJECTS,
            data={
                "job_id": job.get("id", "") or "",
                "job_done": bool(job.get("done", False)),
                "queued_count": len(ids),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_metaobject(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        fields_raw = node.get("fields") or []
        # Surface a flat {key: value} map alongside the typed list —
        # most engines just want the lookup, not the type metadata.
        flat = {}
        typed = []
        for f in fields_raw:
            if not isinstance(f, dict):
                continue
            key = f.get("key", "") or ""
            if key:
                flat[key] = f.get("value", "") or ""
            typed.append({
                "key": key,
                "value": f.get("value", "") or "",
                "type": f.get("type", "") or "",
            })
        return {
            "id": node.get("id", "") or "",
            "type": node.get("type", "") or "",
            "handle": node.get("handle", "") or "",
            "display_name": node.get("displayName", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "fields": typed,
            "field_map": flat,
        }
