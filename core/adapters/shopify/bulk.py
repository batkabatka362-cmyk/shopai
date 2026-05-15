"""ShopifyBulkOperationsAdapter — async bulk export/import.

Bulk operations are Shopify's only sane way to read more than a few
thousand records of one resource. The standard ``products(first: N)``
query caps at 250-per-page and consumes the per-second cost budget;
asking for 100k products that way takes minutes and may rate-limit
the entire app.

The bulk operation runs the query *server-side* and writes a JSONL
file to a Google Cloud Storage URL ShopAI then downloads — one HTTP
request, no pagination, no rate limit. ShopAI's analytics +
data-pipeline engines use this for full-store snapshots.

Capabilities:

  * ``SHOPIFY_RUN_BULK_QUERY``        — start a bulk query.
  * ``SHOPIFY_GET_BULK_OPERATION``    — poll the current bulk op.
  * ``SHOPIFY_CANCEL_BULK_OPERATION`` — cancel an in-flight op.

Workflow::

    # 1. Kick off the export
    r = adapter.execute(SHOPIFY_RUN_BULK_QUERY, {
        "query": '{ products { edges { node { id title } } } }',
    })
    op_id = r.data["bulk_operation"]["id"]

    # 2. Poll until status == "COMPLETED"
    while True:
        s = adapter.execute(SHOPIFY_GET_BULK_OPERATION, {})
        if s.data["bulk_operation"]["status"] in ("COMPLETED", "FAILED",
                                                  "CANCELED"):
            break
        time.sleep(5)

    # 3. Download the JSONL
    url = s.data["bulk_operation"]["url"]   # GCS signed URL

Important Shopify constraints (Pattern E-adjacent):

  * Only ONE bulk operation per shop can run at a time. Starting a
    new one while another is in flight raises a userError.
  * The output URL is a signed GCS URL — valid for ~7 days, then
    expires. Engines must download promptly.
  * Mutations can be bulk too via ``bulkOperationRunMutation`` but
    that takes a JSONL of inputs uploaded via stagedUploads first.
    This adapter ships only the query path; bulk mutations would be
    a Phase 9 follow-up.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BULK_OP_FIELDS = """
id
status
errorCode
type
query
createdAt
completedAt
objectCount
fileSize
url
partialDataUrl
""".strip()


_RUN_BULK_QUERY_MUTATION = f"""
mutation bulkOperationRunQuery($query: String!) {{
  bulkOperationRunQuery(query: $query) {{
    bulkOperation {{
      {_BULK_OP_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_CURRENT_BULK_QUERY = f"""
query currentBulkOperation {{
  currentBulkOperation {{
    {_BULK_OP_FIELDS}
  }}
}}
""".strip()


_CANCEL_BULK_MUTATION = f"""
mutation bulkOperationCancel($id: ID!) {{
  bulkOperationCancel(id: $id) {{
    bulkOperation {{
      {_BULK_OP_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


class ShopifyBulkOperationsAdapter(ShopifyBaseAdapter):
    name = "shopify_bulk"
    capabilities = {
        Capability.SHOPIFY_RUN_BULK_QUERY,
        Capability.SHOPIFY_GET_BULK_OPERATION,
        Capability.SHOPIFY_CANCEL_BULK_OPERATION,
    }
    # Scope depends on the caller's query — the bulk operation
    # surface itself adds no specific scope, but the embedded
    # query inherits whatever read scope it queries against.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_RUN_BULK_QUERY:
            return self._run_query(params)
        if capability == Capability.SHOPIFY_GET_BULK_OPERATION:
            return self._get_current(params)
        if capability == Capability.SHOPIFY_CANCEL_BULK_OPERATION:
            return self._cancel(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Run query ──────────────────────────────────────────────────

    def _run_query(self, params: dict[str, Any]) -> Any:
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name,
                "'query' is required (a GraphQL query string to bulk-run)",
            )
        # Shopify expects the query string passed verbatim; it has
        # subtle parser quirks if the outer braces are missing.
        # Trust the caller — engines compose this from templates.
        data = self._gql(_RUN_BULK_QUERY_MUTATION, {"query": query.strip()})
        self._check_user_errors(data, "bulkOperationRunQuery")
        payload = data.get("bulkOperationRunQuery") or {}
        return self._success(
            Capability.SHOPIFY_RUN_BULK_QUERY,
            data={
                "bulk_operation": self._normalise_op(
                    payload.get("bulkOperation") or {},
                ),
            },
        )

    # ── Get current ────────────────────────────────────────────────

    def _get_current(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_CURRENT_BULK_QUERY, {})
        op = data.get("currentBulkOperation") or {}
        normalised = self._normalise_op(op)
        return self._success(
            Capability.SHOPIFY_GET_BULK_OPERATION,
            data={
                "bulk_operation": normalised,
                "found": bool(op),
                "is_terminal": normalised.get("status", "") in {
                    "COMPLETED", "FAILED", "CANCELED", "EXPIRED",
                },
            },
        )

    # ── Cancel ─────────────────────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        op_id = params.get("id") or params.get("operation_id")
        if not isinstance(op_id, str) or not op_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the bulk operation) is required",
            )
        data = self._gql(_CANCEL_BULK_MUTATION, {"id": op_id.strip()})
        self._check_user_errors(data, "bulkOperationCancel")
        payload = data.get("bulkOperationCancel") or {}
        return self._success(
            Capability.SHOPIFY_CANCEL_BULK_OPERATION,
            data={
                "bulk_operation": self._normalise_op(
                    payload.get("bulkOperation") or {},
                ),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_op(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "type": node.get("type", "") or "",
            "error_code": node.get("errorCode", "") or "",
            "object_count": int(node.get("objectCount") or 0),
            "file_size": int(node.get("fileSize") or 0),
            "url": node.get("url", "") or "",
            "partial_data_url": node.get("partialDataUrl", "") or "",
            "query": node.get("query", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "completed_at": node.get("completedAt", "") or "",
        }
