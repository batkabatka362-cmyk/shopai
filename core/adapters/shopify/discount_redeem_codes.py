"""ShopifyDiscountRedeemCodesAdapter — bulk add/delete redeem codes.

Companion to the discount-CRUD adapters (``discounts.py``,
``discount_code_bxgy.py``, ``discount_code_free_shipping.py``)
plus the bulk-delete-by-discount adapter
(``discount_bulk_delete.py``). The single-code path is covered
by the parent code-discount; this adapter handles the BULK
redeem-code operations beneath an existing code discount:

  * **Add many codes at once.** A single code-discount can
    fan out into 1k+ unique codes (one per influencer, one per
    affiliate, one per recovery email). Engine generates the
    code list locally and submits via
    ``discountRedeemCodeBulkAdd``.
  * **Drop a slice of codes.** When an influencer cohort
    expires, the engine deletes that subset via
    ``discountCodeRedeemCodeBulkDelete`` — using ids,
    search, or savedSearchId.

Capabilities:

  * ``SHOPIFY_BULK_ADD_DISCOUNT_REDEEM_CODES`` —
    discountRedeemCodeBulkAdd. Pattern A: discountId at field
    level + codes list of {code} dicts.
  * ``SHOPIFY_BULK_DELETE_DISCOUNT_REDEEM_CODES`` —
    discountCodeRedeemCodeBulkDelete. Pattern A: discountId
    at field level + exactly ONE selector (ids / search /
    saved_search_id).

UserError variant for both is ``DiscountUserError`` (has code).

Pattern C (already codified — discount_bulk_delete handles
the same trap): the bulk-delete mutation rejects nullable
selector variables sent as `null` alongside the chosen one
with "Only one of IDs, search argument or saved search ID is
allowed". Adapter dynamically composes the GraphQL operation
to declare only the selector actually in use.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BULK_ADD_MUTATION = """
mutation discountRedeemCodeBulkAdd(
  $discountId: ID!,
  $codes: [DiscountRedeemCodeInput!]!
) {
  discountRedeemCodeBulkAdd(
    discountId: $discountId,
    codes: $codes
  ) {
    bulkCreation {
      id
      codesCount
      done
      failedCount
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


# Pattern C: same null-variable trap as discount_bulk_delete —
# emit only the selected key. Three pre-built variants per call.
_BULK_DELETE_BY_IDS = """
mutation discountCodeRedeemCodeBulkDelete($discountId: ID!, $ids: [ID!]) {
  discountCodeRedeemCodeBulkDelete(discountId: $discountId, ids: $ids) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_BY_SEARCH = """
mutation discountCodeRedeemCodeBulkDelete($discountId: ID!, $search: String) {
  discountCodeRedeemCodeBulkDelete(discountId: $discountId, search: $search) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_BULK_DELETE_BY_SAVED_SEARCH = """
mutation discountCodeRedeemCodeBulkDelete(
  $discountId: ID!, $savedSearchId: ID
) {
  discountCodeRedeemCodeBulkDelete(
    discountId: $discountId, savedSearchId: $savedSearchId
  ) {
    job { id done }
    userErrors { field message code }
  }
}
""".strip()


_DELETE_MUTATIONS = {
    "ids": _BULK_DELETE_BY_IDS,
    "search": _BULK_DELETE_BY_SEARCH,
    "savedSearchId": _BULK_DELETE_BY_SAVED_SEARCH,
}


# Shopify caps a single bulk-add at 100 codes per call.
_MAX_CODES_PER_CALL = 100


class ShopifyDiscountRedeemCodesAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_redeem_codes"
    capabilities = {
        Capability.SHOPIFY_BULK_ADD_DISCOUNT_REDEEM_CODES,
        Capability.SHOPIFY_BULK_DELETE_DISCOUNT_REDEEM_CODES,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_BULK_ADD_DISCOUNT_REDEEM_CODES:
            return self._bulk_add(params)
        if capability == \
                Capability.SHOPIFY_BULK_DELETE_DISCOUNT_REDEEM_CODES:
            return self._bulk_delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Bulk add ───────────────────────────────────────────────────

    def _bulk_add(self, params: dict[str, Any]) -> Any:
        discount_id = self._extract_discount_id(params)
        codes = self._build_codes(params.get("codes"))

        # Chunk above 100 — Shopify caps per call.
        bulk_creations: list[dict[str, Any]] = []
        for chunk_start in range(0, len(codes), _MAX_CODES_PER_CALL):
            chunk = codes[chunk_start:chunk_start + _MAX_CODES_PER_CALL]
            data = self._gql(_BULK_ADD_MUTATION, {
                "discountId": discount_id,
                "codes": chunk,
            })
            self._check_user_errors(data, "discountRedeemCodeBulkAdd")
            payload = data.get("discountRedeemCodeBulkAdd") or {}
            creation = payload.get("bulkCreation") or {}
            try:
                codes_count = int(creation.get("codesCount") or 0)
            except (TypeError, ValueError):
                codes_count = 0
            try:
                failed_count = int(creation.get("failedCount") or 0)
            except (TypeError, ValueError):
                failed_count = 0
            bulk_creations.append({
                "id": creation.get("id", "") or "",
                "codes_count": codes_count,
                "failed_count": failed_count,
                "done": bool(creation.get("done", False)),
            })

        return self._success(
            Capability.SHOPIFY_BULK_ADD_DISCOUNT_REDEEM_CODES,
            data={
                "bulk_creations": bulk_creations,
                "requested_count": len(codes),
                "chunks": len(bulk_creations),
            },
        )

    # ── Bulk delete ────────────────────────────────────────────────

    def _bulk_delete(self, params: dict[str, Any]) -> Any:
        discount_id = self._extract_discount_id(params)
        selector_key, selector_value = self._build_delete_selector(params)
        mutation = _DELETE_MUTATIONS[selector_key]
        data = self._gql(mutation, {
            "discountId": discount_id,
            selector_key: selector_value,
        })
        self._check_user_errors(data, "discountCodeRedeemCodeBulkDelete")
        payload = data.get("discountCodeRedeemCodeBulkDelete") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_BULK_DELETE_DISCOUNT_REDEEM_CODES,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
                "selector": self._summarise_selector(
                    selector_key, selector_value,
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_discount_id(self, params: dict[str, Any]) -> str:
        discount_id = (
            params.get("discount_id")
            or params.get("discountId")
            or params.get("id")
        )
        if not isinstance(discount_id, str) or not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'discount_id' (Shopify GID for the code discount) "
                "is required",
            )
        return discount_id.strip()

    def _build_codes(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'codes' must be a non-empty list — strings or "
                "{code: 'XYZ'} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, c in enumerate(raw):
            if isinstance(c, str):
                if not c.strip():
                    raise AdapterValidationError(
                        self.name, f"codes[{i}] is blank",
                    )
                out.append({"code": c.strip()})
                continue
            if not isinstance(c, dict):
                raise AdapterValidationError(
                    self.name,
                    f"codes[{i}] must be a string or {{code}} dict",
                )
            code_str = c.get("code")
            if not isinstance(code_str, str) or not code_str.strip():
                raise AdapterValidationError(
                    self.name,
                    f"codes[{i}] missing 'code' (the literal redeem "
                    "code string)",
                )
            out.append({"code": code_str.strip()})
        return out

    def _build_delete_selector(
        self, params: dict[str, Any],
    ) -> tuple[str, Any]:
        ids = params.get("ids")
        search = params.get("search")
        saved_search_id = (
            params.get("saved_search_id")
            or params.get("savedSearchId")
        )

        present = [
            (name, value) for name, value in (
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
                "'saved_search_id' to identify the codes to delete",
            )
        if len(present) > 1:
            raise AdapterValidationError(
                self.name,
                f"only one of 'ids' / 'search' / 'saved_search_id' "
                f"may be set; got {[n for n, _ in present]}",
            )
        name, value = present[0]
        if name == "ids":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value
            ):
                raise AdapterValidationError(
                    self.name,
                    "'ids' must be a list of redeem-code GID strings",
                )
            cleaned = [v.strip() for v in value if v.strip()]
            if not cleaned:
                raise AdapterValidationError(
                    self.name, "'ids' contained only blanks",
                )
            return "ids", cleaned
        if name == "search":
            if not isinstance(value, str):
                raise AdapterValidationError(
                    self.name, "'search' must be a string",
                )
            return "search", value.strip()
        # saved_search_id
        if not isinstance(value, str):
            raise AdapterValidationError(
                self.name,
                "'saved_search_id' must be a Shopify GID string",
            )
        return "savedSearchId", value.strip()

    @staticmethod
    def _summarise_selector(
        key: str, value: Any,
    ) -> dict[str, Any]:
        if key == "ids":
            return {"kind": "ids", "count": len(value)}
        if key == "search":
            return {"kind": "search", "query": value}
        return {"kind": "saved_search", "saved_search_id": value}
