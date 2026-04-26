"""ShopifyProductDuplicateAdapter — clone a product.

Companion to ``products.py`` (full product CRUD). The clone
operation is special enough to live in its own adapter:

  * **Creative pipeline.** When the creative engine generates a
    new variant of an existing winning product (different photo
    set, different copy, different price tier), it doesn't want
    to recreate the SKU graph from scratch. Duplicate the proven
    parent, then patch the differences.
  * **A/B testing.** Spin up a clone with a new title + DRAFT
    status, run pricing experiments on the clone, promote the
    winner to ACTIVE. Beats hand-editing the original and
    risking customer-facing churn.
  * **Catalog migration.** When merging two markets' catalogs
    into a unified parent catalog, duplicate-then-patch keeps
    the source product intact for rollback.

Capability:

  * ``SHOPIFY_DUPLICATE_PRODUCT`` — productDuplicate. Pattern A:
    productId + newTitle both at field level.

Pattern F: productDuplicate userErrors are typed ``UserError``
(no ``code`` field), unlike most product mutations.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_DUPLICATE_PRODUCT_MUTATION = """
mutation productDuplicate(
  $productId: ID!,
  $newTitle: String!,
  $newStatus: ProductStatus,
  $includeImages: Boolean,
  $includeTranslations: Boolean,
  $synchronous: Boolean
) {
  productDuplicate(
    productId: $productId,
    newTitle: $newTitle,
    newStatus: $newStatus,
    includeImages: $includeImages,
    includeTranslations: $includeTranslations,
    synchronous: $synchronous
  ) {
    newProduct {
      id
      title
      handle
      status
      productType
      vendor
      tags
      createdAt
      updatedAt
    }
    imageJob {
      id
      done
    }
    productDuplicateOperation {
      id
      status
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_VALID_STATUSES = {"ACTIVE", "ARCHIVED", "DRAFT"}


class ShopifyProductDuplicateAdapter(ShopifyBaseAdapter):
    name = "shopify_product_duplicate"
    capabilities = {Capability.SHOPIFY_DUPLICATE_PRODUCT}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_DUPLICATE_PRODUCT:
            return self._duplicate(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _duplicate(self, params: dict[str, Any]) -> Any:
        product_id = params.get("product_id") or params.get("productId")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'product_id' (Shopify GID) is required — Pattern A: "
                "productId at field level",
            )
        new_title = params.get("new_title") or params.get("newTitle")
        if not isinstance(new_title, str) or not new_title.strip():
            raise AdapterValidationError(
                self.name,
                "'new_title' is required (non-empty string)",
            )

        variables: dict[str, Any] = {
            "productId": product_id.strip(),
            "newTitle": new_title.strip(),
        }

        new_status = params.get("new_status") or params.get("newStatus")
        if new_status is not None:
            if not isinstance(new_status, str):
                raise AdapterValidationError(
                    self.name, "'new_status' must be a string",
                )
            up = new_status.strip().upper()
            if up not in _VALID_STATUSES:
                raise AdapterValidationError(
                    self.name,
                    f"'new_status' must be one of {sorted(_VALID_STATUSES)}",
                )
            variables["newStatus"] = up

        for friendly, camel in (
            ("include_images", "includeImages"),
            ("include_translations", "includeTranslations"),
            ("synchronous", "synchronous"),
        ):
            if friendly in params and params[friendly] is not None:
                variables[camel] = bool(params[friendly])
            elif camel in params and params[camel] is not None:
                variables[camel] = bool(params[camel])

        data = self._gql(_DUPLICATE_PRODUCT_MUTATION, variables)
        self._check_user_errors(data, "productDuplicate")
        payload = data.get("productDuplicate") or {}
        new_product = payload.get("newProduct")
        operation = payload.get("productDuplicateOperation") or {}
        image_job = payload.get("imageJob") or {}
        return self._success(
            Capability.SHOPIFY_DUPLICATE_PRODUCT,
            data={
                "new_product": (
                    self._normalise_product(new_product)
                    if isinstance(new_product, dict) else {}
                ),
                "operation_id": (
                    operation.get("id", "")
                    if isinstance(operation, dict) else ""
                ) or "",
                "operation_status": (
                    operation.get("status", "")
                    if isinstance(operation, dict) else ""
                ) or "",
                "image_job_id": (
                    image_job.get("id", "")
                    if isinstance(image_job, dict) else ""
                ) or "",
                "image_job_done": bool(
                    image_job.get("done", False)
                    if isinstance(image_job, dict) else False
                ),
            },
        )

    @staticmethod
    def _normalise_product(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        tags = node.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not isinstance(tags, list):
            tags = []
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "status": node.get("status", "") or "",
            "product_type": node.get("productType", "") or "",
            "vendor": node.get("vendor", "") or "",
            "tags": [str(t) for t in tags],
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
