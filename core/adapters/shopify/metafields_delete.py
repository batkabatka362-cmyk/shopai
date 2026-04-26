"""ShopifyMetafieldsDeleteAdapter — bulk metafield delete.

Companion to ``metafield.py`` (which exposes the SET side via
``metafieldsSet``). The DELETE side is the same one-shot
endpoint shape — give it a list of identifier triples
(``ownerId``, ``namespace``, ``key``) and it removes them all
in one call.

ShopAI's content + cleanup engines lean on this:

  * **GDPR / data-deletion sweeps.** Customer requests their
    data erased; the engine pulls every metafield namespaced
    to that customer's resources and drops them in one batch.
  * **Campaign teardown.** A holiday campaign sprayed
    metafields across hundreds of products
    (``custom.holiday_2025_banner_color``); the cleanup engine
    removes the whole namespace once the campaign window
    closes.
  * **Definition retirement.** When a definition is deleted,
    Shopify orphans the underlying metafields. This adapter
    sweeps them up.

Capability:

  * ``SHOPIFY_DELETE_METAFIELDS`` — metafieldsDelete. Takes a
    list of {owner_id, namespace, key} dicts. Pattern A: the
    list lives at the GraphQL field level, not inside an
    Input dict.

Pattern F: the ``metafieldsDelete`` userErrors are typed
``UserError`` (no ``code`` field). Adapter drops ``code`` from
the userErrors selection.

Shopify caps a single metafieldsDelete call at 25 identifiers
(same limit as metafieldsSet). The adapter chunks larger
payloads automatically rather than failing the call.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# Shopify caps metafieldsDelete at 25 entries per call.
_MAX_PER_CALL = 25


_DELETE_METAFIELDS_MUTATION = """
mutation metafieldsDelete($metafields: [MetafieldIdentifierInput!]!) {
  metafieldsDelete(metafields: $metafields) {
    deletedMetafields {
      ownerId
      namespace
      key
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyMetafieldsDeleteAdapter(ShopifyBaseAdapter):
    name = "shopify_metafields_delete"
    capabilities = {Capability.SHOPIFY_DELETE_METAFIELDS}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_DELETE_METAFIELDS:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _delete(self, params: dict[str, Any]) -> Any:
        identifiers = self._build_identifiers(params.get("metafields"))

        deleted: list[dict[str, str]] = []
        for chunk_start in range(0, len(identifiers), _MAX_PER_CALL):
            chunk = identifiers[chunk_start:chunk_start + _MAX_PER_CALL]
            data = self._gql(_DELETE_METAFIELDS_MUTATION, {
                "metafields": chunk,
            })
            self._check_user_errors(data, "metafieldsDelete")
            payload = data.get("metafieldsDelete") or {}
            for d in (payload.get("deletedMetafields") or []):
                if not isinstance(d, dict):
                    continue
                deleted.append({
                    "owner_id": d.get("ownerId", "") or "",
                    "namespace": d.get("namespace", "") or "",
                    "key": d.get("key", "") or "",
                })

        return self._success(
            Capability.SHOPIFY_DELETE_METAFIELDS,
            data={
                "deleted_metafields": deleted,
                "deleted_count": len(deleted),
                "requested_count": len(identifiers),
            },
        )

    def _build_identifiers(self, raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'metafields' must be a non-empty list of "
                "{owner_id, namespace, key} dicts",
            )
        out: list[dict[str, str]] = []
        for i, m in enumerate(raw):
            if not isinstance(m, dict):
                raise AdapterValidationError(
                    self.name, f"metafields[{i}] must be a dict",
                )
            owner_id = m.get("owner_id") or m.get("ownerId")
            namespace = m.get("namespace")
            key = m.get("key")
            if not isinstance(owner_id, str) or not owner_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"metafields[{i}] missing 'owner_id' (Shopify GID "
                    "for the resource)",
                )
            if not isinstance(namespace, str) or not namespace.strip():
                raise AdapterValidationError(
                    self.name,
                    f"metafields[{i}] missing 'namespace'",
                )
            if not isinstance(key, str) or not key.strip():
                raise AdapterValidationError(
                    self.name,
                    f"metafields[{i}] missing 'key'",
                )
            out.append({
                "ownerId": owner_id.strip(),
                "namespace": namespace.strip(),
                "key": key.strip(),
            })
        return out
