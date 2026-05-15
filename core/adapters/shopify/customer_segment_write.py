"""ShopifyCustomerSegmentWriteAdapter — segment update + delete.

Companion to ``segments.py`` (LIST/QUERY segments + GET members
+ CREATE). The existing adapter mints segments and reads them
back; this one closes the lifecycle with update + delete.

ShopAI's segmentation engine uses these:

  * **Live segment refresh.** Quarterly the engine re-derives
    "high-value buyer" criteria (LTV > $X, repeat orders > N
    in the last 90d) and pushes the new ShopifyQL query string
    via ``segmentUpdate``. The segment GID stays stable so
    downstream marketing flows don't have to re-bind.
  * **Rename for clarity.** Operator-facing labels get tidied
    up — same segment, new name.
  * **Cleanup.** When a campaign-specific segment ("Black
    Friday cart abandoners") expires, ``segmentDelete`` removes
    it so the merchant's segment list stays manageable.

Capabilities:

  * ``SHOPIFY_UPDATE_CUSTOMER_SEGMENT`` — segmentUpdate.
    Pattern A: id at field level. Patchable: name, query.
  * ``SHOPIFY_DELETE_CUSTOMER_SEGMENT`` — segmentDelete.
    Pattern A: id at field level.

Pattern F: both mutations use the typed ``UserError`` (no
``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SEGMENT_FIELDS = """
id
name
query
creationDate
lastEditDate
""".strip()


_UPDATE_SEGMENT_MUTATION = f"""
mutation segmentUpdate($id: ID!, $name: String, $query: String) {{
  segmentUpdate(id: $id, name: $name, query: $query) {{
    segment {{
      {_SEGMENT_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_SEGMENT_MUTATION = """
mutation segmentDelete($id: ID!) {
  segmentDelete(id: $id) {
    deletedSegmentId
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyCustomerSegmentWriteAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_segment_write"
    capabilities = {
        Capability.SHOPIFY_UPDATE_CUSTOMER_SEGMENT,
        Capability.SHOPIFY_DELETE_CUSTOMER_SEGMENT,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_CUSTOMER_SEGMENT:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_CUSTOMER_SEGMENT:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        segment_id = self._extract_id(params)

        variables: dict[str, Any] = {
            "id": segment_id,
            "name": None,
            "query": None,
        }
        any_change = False

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name, "'name' must be a non-empty string",
                )
            variables["name"] = name.strip()
            any_change = True

        query_str = params.get("query")
        if query_str is not None:
            if not isinstance(query_str, str) or not query_str.strip():
                raise AdapterValidationError(
                    self.name,
                    "'query' must be a non-empty ShopifyQL string",
                )
            variables["query"] = query_str.strip()
            any_change = True

        if not any_change:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                "'name' or 'query'",
            )

        data = self._gql(_UPDATE_SEGMENT_MUTATION, variables)
        self._check_user_errors(data, "segmentUpdate")
        payload = data.get("segmentUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER_SEGMENT,
            data={
                "segment": self._normalise_segment(
                    payload.get("segment") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        segment_id = self._extract_id(params)
        data = self._gql(_DELETE_SEGMENT_MUTATION, {"id": segment_id})
        self._check_user_errors(data, "segmentDelete")
        payload = data.get("segmentDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CUSTOMER_SEGMENT,
            data={
                "deleted_id": (
                    payload.get("deletedSegmentId", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        segment_id = (
            params.get("id")
            or params.get("segment_id")
            or params.get("segmentId")
        )
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customer segment) is required",
            )
        return segment_id.strip()

    @staticmethod
    def _normalise_segment(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "query": node.get("query", "") or "",
            "creation_date": node.get("creationDate", "") or "",
            "last_edit_date": node.get("lastEditDate", "") or "",
        }
