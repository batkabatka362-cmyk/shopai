"""ShopifyBulkMutationsAdapter — async bulk WRITE operations.

Companion to ``bulk.py`` (which does bulk *queries*). Bulk mutations
are the only sane way to push 10k+ records of one resource —
inventory adjustments, product imports, customer migrations.

Workflow has THREE wire steps:

  1. ``stagedUploadsCreate`` — Shopify allocates a private GCS bucket
     and returns a signed upload URL. The caller POSTs a JSONL
     payload (one mutation-input dict per line) to that URL.
  2. ``bulkOperationRunMutation`` — caller passes the staged-upload
     resource path; Shopify runs the mutation against every JSONL
     line server-side and writes results to a download URL.
  3. ``currentBulkOperation`` (from ``bulk.py``) — poll until
     status reaches a terminal state, then download the results
     JSONL to learn which lines succeeded.

This adapter ships steps 1 and 2; the actual file upload (step 1.5)
is plain HTTP POST and lives in the data-pipeline layer that
already does signed-URL uploads. Step 3 reuses
``ShopifyBulkOperationsAdapter`` from ``bulk.py``.

Capabilities:

  * ``SHOPIFY_STAGE_UPLOAD``      — get a signed upload URL.
  * ``SHOPIFY_RUN_BULK_MUTATION`` — run the mutation over a JSONL.

Friendly stage-upload call shape::

    {"resource":  "BULK_MUTATION_VARIABLES",  # or "PRODUCT_IMAGE", etc.
     "filename":  "products.jsonl",
     "mime_type": "text/jsonl",
     "size":      "12345",                   # bytes, as string
     "http_method": "POST"}                  # or PUT for some resources

Friendly run-mutation call shape::

    {"mutation":           "mutation call($input: ProductInput!) {...}",
     "staged_upload_path": "tmp/abc/products.jsonl"}

Pattern E note: bulk mutations require both ``write_products`` (or
the corresponding scope for the target resource) AND the bulk
operation feature flag the Shopify Plus tier of plans grants by
default. Smaller plans hit a "feature not available" error at
``bulkOperationRunMutation`` despite having all the OAuth scopes.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_STAGED_UPLOADS_CREATE_MUTATION = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets {
      url
      resourceUrl
      parameters {
        name
        value
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_RUN_BULK_MUTATION = """
mutation bulkOperationRunMutation(
  $mutation: String!,
  $stagedUploadPath: String!
) {
  bulkOperationRunMutation(
    mutation: $mutation,
    stagedUploadPath: $stagedUploadPath
  ) {
    bulkOperation {
      id
      status
      errorCode
      type
      query
      createdAt
      url
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_RESOURCES = {
    "BULK_MUTATION_VARIABLES",
    "COLLECTION_IMAGE",
    "FILE",
    "IMAGE",
    "MODEL_3D",
    "PRODUCT_IMAGE",
    "RETURN_LABEL",
    "SHOP_IMAGE",
    "URL_REDIRECT_IMPORT",
    "VIDEO",
}


_VALID_HTTP_METHODS = {"POST", "PUT"}


class ShopifyBulkMutationsAdapter(ShopifyBaseAdapter):
    name = "shopify_bulk_mutations"
    capabilities = {
        Capability.SHOPIFY_STAGE_UPLOAD,
        Capability.SHOPIFY_RUN_BULK_MUTATION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_STAGE_UPLOAD:
            return self._stage_upload(params)
        if capability == Capability.SHOPIFY_RUN_BULK_MUTATION:
            return self._run_mutation(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Stage upload ───────────────────────────────────────────────

    def _stage_upload(self, params: dict[str, Any]) -> Any:
        upload_input = self._build_staged_input(params)
        data = self._gql(_STAGED_UPLOADS_CREATE_MUTATION, {
            "input": [upload_input],
        })
        self._check_user_errors(data, "stagedUploadsCreate")
        payload = data.get("stagedUploadsCreate") or {}
        targets = payload.get("stagedTargets") or []
        if not targets:
            raise AdapterValidationError(
                self.name,
                "stagedUploadsCreate returned no targets",
            )
        target = targets[0] if isinstance(targets[0], dict) else {}
        return self._success(
            Capability.SHOPIFY_STAGE_UPLOAD,
            data={
                "url": target.get("url", "") or "",
                "resource_url": target.get("resourceUrl", "") or "",
                "parameters": [
                    {
                        "name": p.get("name", "") or "",
                        "value": p.get("value", "") or "",
                    }
                    for p in (target.get("parameters") or [])
                    if isinstance(p, dict)
                ],
            },
        )

    @staticmethod
    def _build_staged_input(params: dict[str, Any]) -> dict[str, Any]:
        resource = params.get("resource")
        if not isinstance(resource, str) or resource not in _VALID_RESOURCES:
            raise AdapterValidationError(
                "shopify_bulk_mutations",
                f"'resource' must be one of: {sorted(_VALID_RESOURCES)}",
            )

        filename = params.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise AdapterValidationError(
                "shopify_bulk_mutations",
                "'filename' is required",
            )

        mime_type = params.get("mime_type") or params.get("mimeType")
        if not isinstance(mime_type, str) or not mime_type.strip():
            raise AdapterValidationError(
                "shopify_bulk_mutations",
                "'mime_type' is required",
            )

        out: dict[str, Any] = {
            "resource": resource,
            "filename": filename.strip(),
            "mimeType": mime_type.strip(),
        }

        # size: Shopify's StagedUploadInput.fileSize is a String
        # representing bytes. Coerce ints/floats so engines don't have
        # to remember the wire format.
        size = params.get("size") or params.get("fileSize")
        if size is not None:
            try:
                size_int = int(size)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_bulk_mutations",
                    "'size' must be numeric (bytes)",
                ) from exc
            if size_int < 0:
                raise AdapterValidationError(
                    "shopify_bulk_mutations",
                    "'size' must be non-negative",
                )
            out["fileSize"] = str(size_int)

        http_method = params.get("http_method") or params.get("httpMethod")
        if http_method is not None:
            if not isinstance(http_method, str):
                raise AdapterValidationError(
                    "shopify_bulk_mutations",
                    "'http_method' must be a string",
                )
            method_upper = http_method.upper()
            if method_upper not in _VALID_HTTP_METHODS:
                raise AdapterValidationError(
                    "shopify_bulk_mutations",
                    f"'http_method' must be one of: "
                    f"{sorted(_VALID_HTTP_METHODS)}",
                )
            out["httpMethod"] = method_upper

        return out

    # ── Run bulk mutation ──────────────────────────────────────────

    def _run_mutation(self, params: dict[str, Any]) -> Any:
        mutation = params.get("mutation")
        if not isinstance(mutation, str) or not mutation.strip():
            raise AdapterValidationError(
                self.name,
                "'mutation' (the GraphQL mutation string) is required",
            )

        staged_path = params.get("staged_upload_path") or params.get(
            "stagedUploadPath"
        )
        if not isinstance(staged_path, str) or not staged_path.strip():
            raise AdapterValidationError(
                self.name,
                "'staged_upload_path' (returned from stagedUploadsCreate) "
                "is required",
            )

        data = self._gql(_RUN_BULK_MUTATION, {
            "mutation": mutation.strip(),
            "stagedUploadPath": staged_path.strip(),
        })
        self._check_user_errors(data, "bulkOperationRunMutation")
        payload = data.get("bulkOperationRunMutation") or {}
        op = payload.get("bulkOperation") or {}
        return self._success(
            Capability.SHOPIFY_RUN_BULK_MUTATION,
            data={
                "bulk_operation": self._normalise_op(op),
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
            "url": node.get("url", "") or "",
            "query": node.get("query", "") or "",
            "created_at": node.get("createdAt", "") or "",
        }
