"""Shopify GraphQL bulk operations.

Amazon-scale catalog reads/writes use the bulk operations
API — Shopify runs a long-running background job that dumps
results to a JSONL URL you poll for. Two flavours:

  * ``bulkOperationRunQuery``  — runs a GraphQL query (for
    exports / reads). Output: a signed S3 URL containing
    JSONL rows.
  * ``bulkOperationRunMutation`` — runs a mutation over a
    pre-staged JSONL input file (for imports). Output: the
    mutation's userErrors + the same JSONL URL.

Only one bulk op can run per shop at a time. Callers should
``cancel()`` the current one before starting a new one.

Typical flow:

    run_id = BulkOperations.run_query(
        client, query="{ products(first: 200) { ... } }",
    )
    # ... poll periodically ...
    status = BulkOperations.current(client)
    if status["status"] == "COMPLETED":
        jsonl_url = status["url"]
        # stream + parse offline

Helpers keep this adapter low-friction for the ~1% of
catalog-size operations that actually need bulk; everyday
reads still use the per-resource adapters.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.bulk_operations",
)


_RUN_QUERY = """
mutation bulkOpRunQuery($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation {
      id status errorCode createdAt completedAt url
      objectCount fileSize
    }
    userErrors { field message }
  }
}
"""


_RUN_MUTATION = """
mutation bulkOpRunMutation(
  $mutation: String!,
  $stagedUploadPath: String!
) {
  bulkOperationRunMutation(
    mutation: $mutation,
    stagedUploadPath: $stagedUploadPath
  ) {
    bulkOperation {
      id status errorCode createdAt url
    }
    userErrors { field message }
  }
}
"""


_CURRENT = """
query currentBulk {
  currentBulkOperation {
    id status errorCode createdAt completedAt url
    objectCount fileSize query
  }
}
"""


_CANCEL = """
mutation bulkOpCancel($id: ID!) {
  bulkOperationCancel(id: $id) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""


def _bulk_gid(bulk_id: int | str) -> str:
    s = str(bulk_id).strip()
    if s.startswith("gid://"):
        return s
    return f"gid://shopify/BulkOperation/{s}"


def _user_errors(
    payload: dict[str, Any], mutation: str,
) -> None:
    errors = (payload.get(mutation) or {}).get(
        "userErrors",
    ) or []
    if errors:
        msgs = "; ".join(
            f"{e.get('field')}: {e.get('message')}"
            for e in errors if isinstance(e, dict)
        )
        raise ShopifyAdminError(
            f"{mutation} userErrors: {msgs}",
            path="graphql.json",
            body=str(payload),
        )


def _normalise_op(
    op: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(op, dict):
        return {}
    return {
        "id": str(op.get("id") or ""),
        "status": str(op.get("status") or ""),
        "error_code": str(op.get("errorCode") or ""),
        "created_at": str(op.get("createdAt") or ""),
        "completed_at": str(op.get("completedAt") or ""),
        "url": str(op.get("url") or ""),
        "object_count": int(
            op.get("objectCount") or 0
            if op.get("objectCount") else 0,
        ) if op.get("objectCount") else 0,
        "file_size": int(
            op.get("fileSize") or 0,
        ) if op.get("fileSize") else 0,
        "query": str(op.get("query") or ""),
    }


class BulkOperations:
    """Thin wrapper over GraphQL bulk-op surface."""

    @staticmethod
    def run_query(
        client: ShopifyAdminClient,
        query: str,
    ) -> dict[str, Any]:
        """Starts a bulk-query job. Returns the normalised
        op record; caller polls ``current()`` to watch for
        completion."""
        if not query or not query.strip():
            raise ValueError("query: required")
        result = client.graphql(
            _RUN_QUERY, variables={"query": query},
        )
        payload = result.get("data") or {}
        _user_errors(payload, "bulkOperationRunQuery")
        op = (
            payload.get("bulkOperationRunQuery") or {}
        ).get("bulkOperation")
        normalised = _normalise_op(op)
        if not normalised.get("id"):
            raise ShopifyAdminError(
                "bulkOperationRunQuery returned no id",
                path="graphql.json",
            )
        return normalised

    @staticmethod
    def run_mutation(
        client: ShopifyAdminClient,
        *,
        mutation: str,
        staged_upload_path: str,
    ) -> dict[str, Any]:
        """Starts a bulk-mutation job against a pre-staged
        JSONL input file uploaded via the
        ``stagedUploadsCreate`` mutation. Out of scope:
        this adapter doesn't stage the upload — caller
        handles that + passes us the resulting path."""
        if not mutation or not mutation.strip():
            raise ValueError("mutation: required")
        if not staged_upload_path:
            raise ValueError(
                "staged_upload_path: required",
            )
        result = client.graphql(
            _RUN_MUTATION,
            variables={
                "mutation": mutation,
                "stagedUploadPath": staged_upload_path,
            },
        )
        payload = result.get("data") or {}
        _user_errors(payload, "bulkOperationRunMutation")
        op = (
            payload.get("bulkOperationRunMutation") or {}
        ).get("bulkOperation")
        normalised = _normalise_op(op)
        if not normalised.get("id"):
            raise ShopifyAdminError(
                "bulkOperationRunMutation returned no id",
                path="graphql.json",
            )
        return normalised

    @staticmethod
    def current(
        client: ShopifyAdminClient,
    ) -> dict[str, Any]:
        """Status of the currently-running (or most
        recently completed) bulk op. Returns an empty dict
        when no op exists yet."""
        result = client.graphql(_CURRENT)
        op = (result.get("data") or {}).get(
            "currentBulkOperation",
        )
        return _normalise_op(op)

    @staticmethod
    def cancel(
        client: ShopifyAdminClient,
        bulk_id: int | str,
    ) -> dict[str, Any]:
        result = client.graphql(
            _CANCEL,
            variables={"id": _bulk_gid(bulk_id)},
        )
        payload = result.get("data") or {}
        _user_errors(payload, "bulkOperationCancel")
        op = (
            payload.get("bulkOperationCancel") or {}
        ).get("bulkOperation")
        return _normalise_op(op)
