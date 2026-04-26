"""ShopifyCustomerMergeAdapter — dedup duplicate customer records.

When the same person checks out twice with different emails, gets
re-imported from a CRM, or migrates from a legacy storefront, the
shop ends up with multiple customer records that are functionally
the same person. ShopAI's segmentation engine reads these duplicates
and the cleanup engine merges them — preserving order history and
LTV signal in one record rather than fragmented across two.

The merge is asynchronous: a job is enqueued, runs in the
background, and reports completion via ``customerMergeJob`` polling.
The companion preview mutation lets engines QA the merge resolution
(which addresses survive, which marketing consent flag wins) before
firing the destructive merge.

Capabilities:

  * ``SHOPIFY_PREVIEW_CUSTOMER_MERGE`` — dry-run; returns the merged
    customer shape that WOULD result.
  * ``SHOPIFY_MERGE_CUSTOMERS``        — enqueue the actual merge.
  * ``SHOPIFY_GET_CUSTOMER_MERGE_JOB`` — poll a previously-enqueued
    job for completion.

Friendly call shape::

    {"customer_one_id": "gid://shopify/Customer/c1",
     "customer_two_id": "gid://shopify/Customer/c2",
     "override_fields": {
        "customer_id_of_default_address": "gid://shopify/Customer/c1",
        "customer_id_of_email": "gid://shopify/Customer/c2",
        "customer_id_of_first_name": "gid://shopify/Customer/c1",
        "customer_id_of_last_name": "gid://shopify/Customer/c1",
        "customer_id_of_phone_number": "gid://shopify/Customer/c2",
        "note": "Combined: dup from CRM import",
        "tags": ["merged-2026-q2"],
     }}

Pattern A: customerMerge takes both customer GIDs at the field level
(not as a list inside an Input dict). The override_fields wraps to
``overrideFields: CustomerMergeOverrideFields``.

Pattern E note: gated by ``write_customers`` scope. Merge is
DESTRUCTIVE — one customer record gets soft-deleted; the engine
should always run preview first and surface the resolution to a
human (or at least an audit log) before committing.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Pattern D: CustomerMergePreview's blockingFields / alternateFields /
# defaultFields are TYPED OBJECTS in 2024-01 with internal structures
# that aren't documented in a way that lets the adapter assemble a
# detailed selection without per-conflict-type expansion. The
# customerMergeErrors variant fields are also opaque enough that we
# only confirm the wire shape. Engines that need detailed inspection
# call the merge mutation and inspect its userErrors.
#
# Also: there's no `resultingCustomer` field — the post-merge customer
# is reachable only via a follow-up customer(id:) query after the
# actual merge runs.
_PREVIEW_CUSTOMER_MERGE_QUERY = """
query customerMergePreview(
  $customerOneId: ID!,
  $customerTwoId: ID!,
  $overrideFields: CustomerMergeOverrideFields
) {
  customerMergePreview(
    customerOneId: $customerOneId,
    customerTwoId: $customerTwoId,
    overrideFields: $overrideFields
  ) {
    customerMergeErrors {
      __typename
    }
    blockingFields { __typename }
    alternateFields { __typename }
    defaultFields { __typename }
  }
}
""".strip()


_MERGE_CUSTOMERS_MUTATION = """
mutation customerMerge(
  $customerOneId: ID!,
  $customerTwoId: ID!,
  $overrideFields: CustomerMergeOverrideFields
) {
  customerMerge(
    customerOneId: $customerOneId,
    customerTwoId: $customerTwoId,
    overrideFields: $overrideFields
  ) {
    job {
      id
      done
    }
    resultingCustomerId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_GET_CUSTOMER_MERGE_JOB_QUERY = """
query customerMergeJob($jobId: ID!) {
  customerMergeJobStatus(jobId: $jobId) {
    job {
      id
      done
    }
    status
    resultingCustomerId
    errors {
      field
      message
      code
    }
  }
}
""".strip()


_OVERRIDE_FIELD_MAP = {
    "customer_id_of_default_address": "customerIdOfDefaultAddress",
    "customer_id_of_email": "customerIdOfEmail",
    "customer_id_of_first_name": "customerIdOfFirstName",
    "customer_id_of_last_name": "customerIdOfLastName",
    "customer_id_of_phone_number": "customerIdOfPhoneNumber",
    "note": "note",
}


class ShopifyCustomerMergeAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_merge"
    capabilities = {
        Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
        Capability.SHOPIFY_MERGE_CUSTOMERS,
        Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE:
            return self._preview(params)
        if capability == Capability.SHOPIFY_MERGE_CUSTOMERS:
            return self._merge(params)
        if capability == Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB:
            return self._get_job(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Preview ────────────────────────────────────────────────────

    def _preview(self, params: dict[str, Any]) -> Any:
        c1, c2 = self._require_customer_pair(params)
        variables: dict[str, Any] = {
            "customerOneId": c1,
            "customerTwoId": c2,
        }
        override = self._build_override_fields(params)
        if override:
            variables["overrideFields"] = override

        data = self._gql(_PREVIEW_CUSTOMER_MERGE_QUERY, variables)
        payload = data.get("customerMergePreview") or {}
        merge_errors = self._presence(payload.get("customerMergeErrors"))
        blocking = self._presence(payload.get("blockingFields"))
        alternate = self._presence(payload.get("alternateFields"))
        default = self._presence(payload.get("defaultFields"))
        return self._success(
            Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
            data={
                # has_* flags are the opaque "is there structured
                # conflict data here?" signal. Detailed inspection
                # lives in the merge mutation's userErrors path.
                "has_merge_errors": bool(merge_errors),
                "merge_error_count": (
                    len(merge_errors)
                    if isinstance(merge_errors, list) else 0
                ),
                "has_blocking_fields": bool(blocking),
                "has_alternate_fields": bool(alternate),
                "has_default_fields": bool(default),
                "is_blocked": bool(merge_errors) or bool(blocking),
            },
        )

    @staticmethod
    def _presence(node: Any) -> Any:
        """Empty list / dict / None → falsy (no conflicts). Anything
        else → truthy. Used to derive has_* flags from the typed
        wrappers without expanding their internal structure."""
        if node is None:
            return None
        if isinstance(node, (list, dict)) and not node:
            return None
        return node

    # ── Merge ──────────────────────────────────────────────────────

    def _merge(self, params: dict[str, Any]) -> Any:
        c1, c2 = self._require_customer_pair(params)
        variables: dict[str, Any] = {
            "customerOneId": c1,
            "customerTwoId": c2,
        }
        override = self._build_override_fields(params)
        if override:
            variables["overrideFields"] = override

        data = self._gql(_MERGE_CUSTOMERS_MUTATION, variables)
        self._check_user_errors(data, "customerMerge")
        payload = data.get("customerMerge") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_MERGE_CUSTOMERS,
            data={
                "job_id": job.get("id", "") or "",
                "job_done": bool(job.get("done", False)),
                "resulting_customer_id": (
                    payload.get("resultingCustomerId", "") or ""
                ),
            },
        )

    # ── Get merge job ─────────────────────────────────────────────

    def _get_job(self, params: dict[str, Any]) -> Any:
        job_id = params.get("job_id") or params.get("id") or params.get(
            "jobId"
        )
        if not isinstance(job_id, str) or not job_id.strip():
            raise AdapterValidationError(
                self.name,
                "'job_id' (Shopify GID for the merge job) is required",
            )
        data = self._gql(_GET_CUSTOMER_MERGE_JOB_QUERY, {
            "jobId": job_id.strip(),
        })
        payload = data.get("customerMergeJobStatus") or {}
        job = payload.get("job") or {}
        errors_raw = payload.get("errors") or []
        errors = [
            {
                "field": ".".join(e.get("field", []) or []),
                "message": e.get("message", "") or "",
                "code": e.get("code", "") or "",
            }
            for e in errors_raw if isinstance(e, dict)
        ]
        return self._success(
            Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB,
            data={
                "job_id": job.get("id", "") or "",
                "job_done": bool(job.get("done", False)),
                "status": payload.get("status", "") or "",
                "resulting_customer_id": (
                    payload.get("resultingCustomerId", "") or ""
                ),
                "errors": errors,
                "is_terminal": payload.get("status", "") in {
                    "COMPLETED", "FAILED",
                },
            },
        )

    # ── Input helpers ──────────────────────────────────────────────

    def _require_customer_pair(
        self, params: dict[str, Any],
    ) -> tuple[str, str]:
        c1 = params.get("customer_one_id") or params.get("customerOneId")
        c2 = params.get("customer_two_id") or params.get("customerTwoId")
        if not isinstance(c1, str) or not c1.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_one_id' (Shopify GID) is required",
            )
        if not isinstance(c2, str) or not c2.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_two_id' (Shopify GID) is required",
            )
        if c1.strip() == c2.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_one_id' and 'customer_two_id' must differ",
            )
        return c1.strip(), c2.strip()

    def _build_override_fields(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        raw = params.get("override_fields") or params.get("overrideFields")
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'override_fields' must be a dict",
            )
        out: dict[str, Any] = {}
        for snake, camel in _OVERRIDE_FIELD_MAP.items():
            value = raw.get(snake)
            if value is None:
                value = raw.get(camel)
            if value is None:
                continue
            if not isinstance(value, str):
                raise AdapterValidationError(
                    self.name,
                    f"override_fields.{snake} must be a string",
                )
            out[camel] = value

        tags = raw.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    self.name,
                    "override_fields.tags must be a list of strings",
                )
            out["tags"] = tags

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_customer(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        amount_spent = node.get("amountSpent") or {}
        return {
            "id": node.get("id", "") or "",
            "first_name": node.get("firstName", "") or "",
            "last_name": node.get("lastName", "") or "",
            "email": node.get("email", "") or "",
            "phone": node.get("phone", "") or "",
            "note": node.get("note", "") or "",
            "tags": list(node.get("tags") or []),
            "orders_count": int(node.get("numberOfOrders") or 0),
            "total_spent": (
                amount_spent.get("amount", "")
                if isinstance(amount_spent, dict) else ""
            ) or "",
            "currency_code": (
                amount_spent.get("currencyCode", "")
                if isinstance(amount_spent, dict) else ""
            ) or "",
        }
