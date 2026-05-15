"""ShopifyDiscountBulkDeleteAdapter — bulk delete discounts.

Companion to the discount-CRUD adapters (``discounts.py``,
``discount_automatic.py``, ``discount_automatic_bxgy.py``,
``discount_code_bxgy.py``, ``discount_code_free_shipping.py``,
``discount_activate.py``). Single-record delete is covered;
this adapter wraps the BULK delete primitives that operate on
many discounts in one async job.

ShopAI's promotion + cleanup engines need this:

  * **Campaign sunset.** End-of-quarter sweep that drops every
    automatic discount tagged with the closed campaign's
    saved search.
  * **Migration cleanup.** When the pricing engine flips
    pricing models, retire the old code-discount catalog in
    one job rather than 500 individual delete calls.
  * **Compliance / audit.** Drop discounts associated with a
    deactivated app or de-listed merchant tier.

Capabilities:

  * ``SHOPIFY_BULK_DELETE_AUTOMATIC_DISCOUNTS`` —
    discountAutomaticBulkDelete.
  * ``SHOPIFY_BULK_DELETE_CODE_DISCOUNTS`` —
    discountCodeBulkDelete.

Both mutations accept ANY ONE of three selectors at the
GraphQL field level (Pattern A):

  * ``ids`` — explicit list of discount-node GIDs.
  * ``search`` — search string (matches discount titles /
    codes).
  * ``saved_search_id`` — pre-saved admin filter.

The adapter validates that exactly one is supplied — passing
multiple or none returns AdapterValidationError before the
GraphQL hop.

Both mutations return a Job (the bulk delete runs async). The
job_id can be polled later via the existing bulk-operation
read paths.

UserError variant for both is ``DiscountUserError`` (has
``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Pattern C (codified): Shopify treats variables passed as `null`
# alongside the chosen selector as "set", returning "Only one of
# IDs, search argument or saved search ID is allowed". The fix is
# to send only the variable for the chosen selector — other args
# in the mutation field stay omitted (not set to $variable=null).
# We pre-build three query variants and route to the right one.
_BULK_DELETE_AUTOMATIC_BY_IDS = """
mutation discountAutomaticBulkDelete($ids: [ID!]) {
  discountAutomaticBulkDelete(ids: $ids) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_AUTOMATIC_BY_SEARCH = """
mutation discountAutomaticBulkDelete($search: String) {
  discountAutomaticBulkDelete(search: $search) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_AUTOMATIC_BY_SAVED_SEARCH = """
mutation discountAutomaticBulkDelete($savedSearchId: ID) {
  discountAutomaticBulkDelete(savedSearchId: $savedSearchId) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_CODE_BY_IDS = """
mutation discountCodeBulkDelete($ids: [ID!]) {
  discountCodeBulkDelete(ids: $ids) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_CODE_BY_SEARCH = """
mutation discountCodeBulkDelete($search: String) {
  discountCodeBulkDelete(search: $search) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_CODE_BY_SAVED_SEARCH = """
mutation discountCodeBulkDelete($savedSearchId: ID) {
  discountCodeBulkDelete(savedSearchId: $savedSearchId) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_AUTOMATIC_MUTATIONS = {
    "ids": _BULK_DELETE_AUTOMATIC_BY_IDS,
    "search": _BULK_DELETE_AUTOMATIC_BY_SEARCH,
    "savedSearchId": _BULK_DELETE_AUTOMATIC_BY_SAVED_SEARCH,
}


_CODE_MUTATIONS = {
    "ids": _BULK_DELETE_CODE_BY_IDS,
    "search": _BULK_DELETE_CODE_BY_SEARCH,
    "savedSearchId": _BULK_DELETE_CODE_BY_SAVED_SEARCH,
}


class ShopifyDiscountBulkDeleteAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_bulk_delete"
    capabilities = {
        Capability.SHOPIFY_BULK_DELETE_AUTOMATIC_DISCOUNTS,
        Capability.SHOPIFY_BULK_DELETE_CODE_DISCOUNTS,
    }
    required_scopes = frozenset({"write_discounts"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_BULK_DELETE_AUTOMATIC_DISCOUNTS:
            return self._bulk_delete(
                params, _AUTOMATIC_MUTATIONS,
                "discountAutomaticBulkDelete",
                Capability.SHOPIFY_BULK_DELETE_AUTOMATIC_DISCOUNTS,
            )
        if capability == Capability.SHOPIFY_BULK_DELETE_CODE_DISCOUNTS:
            return self._bulk_delete(
                params, _CODE_MUTATIONS,
                "discountCodeBulkDelete",
                Capability.SHOPIFY_BULK_DELETE_CODE_DISCOUNTS,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _bulk_delete(
        self,
        params: dict[str, Any],
        mutations: dict[str, str],
        op_name: str,
        capability: Capability,
    ) -> Any:
        variables = self._build_selector_variables(params)
        # Variables dict has exactly one key — pick the matching
        # mutation variant.
        selector_key = next(iter(variables))
        mutation = mutations[selector_key]
        data = self._gql(mutation, variables)
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        job = payload.get("job") or {}
        return self._success(
            capability,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
                "selector": self._summarise_selector(variables),
            },
        )

    def _build_selector_variables(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        # Exactly ONE of ids / search / saved_search_id is required.
        ids = params.get("ids")
        search = params.get("search")
        saved_search_id = (
            params.get("saved_search_id") or params.get("savedSearchId")
        )

        present = [
            name for name, value in (
                ("ids", ids),
                ("search", search),
                ("saved_search_id", saved_search_id),
            )
            if value not in (None, "", [])
        ]
        if not present:
            raise AdapterValidationError(
                self.name,
                "supply exactly one of 'ids' / 'search' / "
                "'saved_search_id' — pick the selector that "
                "matches the engine's discount-pool query",
            )
        if len(present) > 1:
            raise AdapterValidationError(
                self.name,
                f"only one of 'ids' / 'search' / 'saved_search_id' "
                f"may be set; got {present}",
            )

        # Pattern C: Shopify rejects this call with "Only one of IDs,
        # search argument or saved search ID is allowed" if any of the
        # nullable variables is sent as `null` alongside the chosen
        # one. The mutation treats `null` as "set" rather than
        # "absent". Only emit the selected key.
        if ids is not None and ids != []:
            if isinstance(ids, str):
                ids = [ids]
            if not isinstance(ids, list) or not all(
                isinstance(i, str) for i in ids
            ):
                raise AdapterValidationError(
                    self.name,
                    "'ids' must be a list of discount-node GID strings",
                )
            cleaned = [i.strip() for i in ids if i.strip()]
            if not cleaned:
                raise AdapterValidationError(
                    self.name, "'ids' contained only blanks",
                )
            return {"ids": cleaned}
        if search:
            if not isinstance(search, str):
                raise AdapterValidationError(
                    self.name, "'search' must be a string",
                )
            return {"search": search.strip()}
        if not isinstance(saved_search_id, str):
            raise AdapterValidationError(
                self.name,
                "'saved_search_id' must be a Shopify GID string",
            )
        return {"savedSearchId": saved_search_id.strip()}

    @staticmethod
    def _summarise_selector(
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        if "ids" in variables:
            return {"kind": "ids", "count": len(variables["ids"])}
        if "search" in variables:
            return {"kind": "search", "query": variables["search"]}
        if "savedSearchId" in variables:
            return {
                "kind": "saved_search",
                "saved_search_id": variables["savedSearchId"],
            }
        return {}
