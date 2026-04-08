"""ShopifyMetafieldAdapter — extended metafield CRUD.

Metafields are Shopify's "attach arbitrary structured data to
any record" feature. ShopAI uses them as a cross-engine memory
layer: brain decisions, learning outcomes, AI-generated content,
agent state — all of it can hang off the relevant Shopify object
without an external database.

The legacy ``utils/shopify_client`` only supports product
metafields. This adapter extends coverage to ORDER, CUSTOMER,
and VARIANT metafields via the ``metafieldsSet`` mutation, which
is the modern bulk-write entry point (replaces the old
per-resource ``productUpdate`` etc. trick).

Capabilities:

  * ``SHOPIFY_SET_METAFIELD`` — write 1..N metafields in one call

Operations are batched: pass a list of ``{owner_id, namespace,
key, type, value}`` and the adapter sends them in a single
GraphQL mutation. Shopify accepts up to 25 metafields per
``metafieldsSet`` call — the adapter chunks larger payloads
automatically.

Owner ID format:

    Order:    "gid://shopify/Order/12345"
    Customer: "gid://shopify/Customer/67890"
    Variant:  "gid://shopify/ProductVariant/abc"
    Product:  "gid://shopify/Product/xyz"
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_METAFIELDS_SET_MUTATION = """
mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields {
      id
      key
      namespace
      ownerType
      type
      value
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


# Shopify caps metafieldsSet at 25 entries per call. Anything
# larger MUST be chunked or the request is rejected with
# userErrors. We chunk at the API limit; callers don't need to
# know.
_BATCH_SIZE = 25


class ShopifyMetafieldAdapter(ShopifyBaseAdapter):
    name = "shopify_metafield"
    capabilities = {Capability.SHOPIFY_SET_METAFIELD}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_SET_METAFIELD:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        metafields = params.get("metafields")
        if not isinstance(metafields, list) or not metafields:
            raise AdapterValidationError(
                self.name, "'metafields' must be a non-empty list",
            )

        normalised = self._normalise(metafields)

        # Chunk to satisfy Shopify's 25-per-call limit. The
        # router records latency for the OUTER call regardless;
        # we accumulate per-chunk results so the caller still
        # sees one envelope.
        all_written: list[dict[str, Any]] = []
        chunks = [
            normalised[i:i + _BATCH_SIZE]
            for i in range(0, len(normalised), _BATCH_SIZE)
        ]
        for chunk in chunks:
            data = self._gql(
                _METAFIELDS_SET_MUTATION,
                {"metafields": chunk},
            )
            self._check_user_errors(data, "metafieldsSet")
            payload = data.get("metafieldsSet") or {}
            all_written.extend(payload.get("metafields") or [])

        return self._success(
            Capability.SHOPIFY_SET_METAFIELD,
            data={
                "written": len(all_written),
                "chunks": len(chunks),
                "metafields": all_written,
            },
        )

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _normalise(metafields: list[Any]) -> list[dict[str, Any]]:
        """Convert ShopAI-friendly dict shape into the
        ``MetafieldsSetInput`` format Shopify expects.

        ShopAI input::

            {
                "owner_id":  "gid://shopify/Order/123",
                "namespace": "shopai",
                "key":       "fraud_score",
                "type":      "number_decimal",
                "value":     "0.42",
            }

        Shopify input::

            {
                "ownerId":   "gid://shopify/Order/123",
                "namespace": "shopai",
                "key":       "fraud_score",
                "type":      "number_decimal",
                "value":     "0.42",
            }

        Raises ``AdapterValidationError`` on missing fields so
        the call fails fast instead of hitting Shopify with a
        userErrors response.
        """
        out: list[dict[str, Any]] = []
        for i, mf in enumerate(metafields):
            if not isinstance(mf, dict):
                raise AdapterValidationError(
                    "shopify_metafield",
                    f"metafields[{i}] is not a dict",
                )
            owner_id = mf.get("owner_id") or mf.get("ownerId")
            namespace = mf.get("namespace") or "shopai"
            key = mf.get("key")
            type_ = mf.get("type") or "single_line_text_field"
            value = mf.get("value")

            missing = []
            if not owner_id:
                missing.append("owner_id")
            if not key:
                missing.append("key")
            if value is None:
                missing.append("value")
            if missing:
                raise AdapterValidationError(
                    "shopify_metafield",
                    f"metafields[{i}] missing: {', '.join(missing)}",
                )

            out.append({
                "ownerId": owner_id,
                "namespace": namespace,
                "key": key,
                "type": type_,
                # Shopify always wants the value as a string,
                # even for numeric / json_string types.
                "value": str(value) if not isinstance(value, str) else value,
            })
        return out
