"""ShopifyDiscountAdapter — code-based percentage and amount discounts.

Shopify's discount surface is split between *automatic* discounts (applied
without a code) and *code* discounts (customer types in a code at
checkout). ShopAI's pricing engine + ROAS guardrails want the *code*
variant: the engine decides "20% off SUMMER25 between dates X and Y for
customers segment Z" and needs a single call to mint the code on the
storefront.

This adapter exposes two capabilities:

  * ``SHOPIFY_CREATE_DISCOUNT`` — create a code-based percentage OR
    fixed-amount discount via ``discountCodeBasicCreate``.
  * ``SHOPIFY_LIST_DISCOUNTS`` — page through existing code discounts
    via ``codeDiscountNodes``.

Friendly call shape so the engine doesn't have to write GraphQL::

    adapter.execute(Capability.SHOPIFY_CREATE_DISCOUNT, {
        "title":     "Summer 25%",
        "code":      "SUMMER25",
        "percentage": 25,                      # OR "amount": 10.00
        "starts_at": "2026-06-01T00:00:00Z",   # optional, default now
        "ends_at":   "2026-08-31T23:59:59Z",   # optional, default open
        "usage_limit": 500,                    # optional, default unlimited
        "applies_once_per_customer": True,     # optional, default True
    })

Validation is done before the GraphQL call so callers fail fast on bad
shapes instead of paying a network round-trip for a userErrors envelope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_DISCOUNT_MUTATION = """
mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
    codeDiscountNode {
      id
      codeDiscount {
        ... on DiscountCodeBasic {
          title
          summary
          status
          startsAt
          endsAt
          usageLimit
          appliesOncePerCustomer
          codes(first: 1) {
            nodes { code }
          }
        }
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_LIST_DISCOUNTS_QUERY = """
query codeDiscountNodes($first: Int!, $after: String) {
  codeDiscountNodes(first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        codeDiscount {
          ... on DiscountCodeBasic {
            title
            summary
            status
            startsAt
            endsAt
            usageLimit
            asyncUsageCount
            appliesOncePerCustomer
            codes(first: 1) {
              nodes { code }
            }
          }
        }
      }
    }
  }
}
""".strip()


# Shopify caps codeDiscountNodes at 250 per call. Keep our default low
# (50) so a single page fits comfortably under the 1000-points GraphQL
# cost budget. Callers who need more can paginate via ``cursor``.
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyDiscountAdapter(ShopifyBaseAdapter):
    name = "shopify_discount"
    capabilities = {
        Capability.SHOPIFY_CREATE_DISCOUNT,
        Capability.SHOPIFY_LIST_DISCOUNTS,
    }
    # Discounts use a dedicated scope pair distinct from products.
    required_scopes = frozenset({
        "read_discounts", "write_discounts",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_DISCOUNT:
            return self._create_discount(params)
        if capability == Capability.SHOPIFY_LIST_DISCOUNTS:
            return self._list_discounts(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create_discount(self, params: dict[str, Any]) -> Any:
        basic_input = self._build_basic_input(params)
        data = self._gql(
            _CREATE_DISCOUNT_MUTATION,
            {"basicCodeDiscount": basic_input},
        )
        self._check_user_errors(data, "discountCodeBasicCreate")
        payload = data.get("discountCodeBasicCreate") or {}
        node = payload.get("codeDiscountNode") or {}
        code_discount = node.get("codeDiscount") or {}
        code_nodes = (code_discount.get("codes") or {}).get("nodes") or []
        return self._success(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            data={
                "id": node.get("id", ""),
                "title": code_discount.get("title", ""),
                "code": code_nodes[0].get("code", "") if code_nodes else "",
                "summary": code_discount.get("summary", ""),
                "status": code_discount.get("status", ""),
                "starts_at": code_discount.get("startsAt", ""),
                "ends_at": code_discount.get("endsAt", ""),
                "usage_limit": code_discount.get("usageLimit"),
                "applies_once_per_customer": code_discount.get(
                    "appliesOncePerCustomer", True
                ),
            },
        )

    @staticmethod
    def _build_basic_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly params dict into a
        ``DiscountCodeBasicInput`` for the GraphQL mutation.

        Validates required fields, mutual exclusivity of percentage vs
        amount, and types — so a misuse fails before hitting Shopify.
        """
        title = params.get("title")
        code = params.get("code")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                "shopify_discount", "'title' is required (non-empty string)",
            )
        if not isinstance(code, str) or not code.strip():
            raise AdapterValidationError(
                "shopify_discount", "'code' is required (non-empty string)",
            )

        percentage = params.get("percentage")
        amount = params.get("amount")
        if percentage is None and amount is None:
            raise AdapterValidationError(
                "shopify_discount",
                "either 'percentage' or 'amount' must be provided",
            )
        if percentage is not None and amount is not None:
            raise AdapterValidationError(
                "shopify_discount",
                "'percentage' and 'amount' are mutually exclusive",
            )

        # Build customerGets value branch
        customer_gets_value: dict[str, Any]
        if percentage is not None:
            try:
                pct = float(percentage)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'percentage' must be numeric, got {type(percentage).__name__}",
                ) from exc
            if not (0 < pct <= 100):
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'percentage' must be in (0, 100], got {pct}",
                )
            # Shopify expects a 0-1 fraction (0.25 == 25%) for
            # DiscountPercentageValueInput.percentage.
            customer_gets_value = {"percentage": pct / 100.0}
        else:
            try:
                amt = float(amount)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'amount' must be numeric, got {type(amount).__name__}",
                ) from exc
            if amt <= 0:
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'amount' must be > 0, got {amt}",
                )
            currency = params.get("currency_code", "USD")
            customer_gets_value = {
                "discountAmount": {
                    "amount": f"{amt:.2f}",
                    "appliesOnEachItem": False,
                },
            }
            # currency_code lives at the parent level for amount-based
            # discounts; Shopify reads it from the shop config so we
            # don't need to pass it explicitly. Keep the param so
            # callers can document intent without breaking the call.
            _ = currency

        out: dict[str, Any] = {
            "title": title.strip(),
            "code": code.strip(),
            "customerSelection": {"all": True},
            "customerGets": {
                "value": customer_gets_value,
                "items": {"all": True},
            },
            "appliesOncePerCustomer": bool(
                params.get("applies_once_per_customer", True)
            ),
        }

        starts_at = params.get("starts_at")
        if starts_at:
            if not isinstance(starts_at, str):
                raise AdapterValidationError(
                    "shopify_discount",
                    "'starts_at' must be an ISO-8601 string",
                )
            out["startsAt"] = starts_at
        ends_at = params.get("ends_at")
        if ends_at:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    "shopify_discount",
                    "'ends_at' must be an ISO-8601 string",
                )
            out["endsAt"] = ends_at

        usage_limit = params.get("usage_limit")
        if usage_limit is not None:
            try:
                ul = int(usage_limit)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'usage_limit' must be int, got {type(usage_limit).__name__}",
                ) from exc
            if ul <= 0:
                raise AdapterValidationError(
                    "shopify_discount",
                    f"'usage_limit' must be > 0, got {ul}",
                )
            out["usageLimit"] = ul

        return out

    # ── List ───────────────────────────────────────────────────────

    def _list_discounts(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_discount", "'cursor' must be a string or None",
            )

        data = self._gql(
            _LIST_DISCOUNTS_QUERY,
            {"first": limit, "after": cursor},
        )
        envelope = data.get("codeDiscountNodes") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        discounts: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            cd = node.get("codeDiscount") or {}
            code_nodes = (cd.get("codes") or {}).get("nodes") or []
            discounts.append({
                "id": node.get("id", ""),
                "title": cd.get("title", ""),
                "code": code_nodes[0].get("code", "") if code_nodes else "",
                "summary": cd.get("summary", ""),
                "status": cd.get("status", ""),
                "starts_at": cd.get("startsAt", ""),
                "ends_at": cd.get("endsAt", ""),
                "usage_limit": cd.get("usageLimit"),
                "usage_count": cd.get("asyncUsageCount", 0),
                "applies_once_per_customer": cd.get(
                    "appliesOncePerCustomer", True
                ),
            })

        return self._success(
            Capability.SHOPIFY_LIST_DISCOUNTS,
            data={
                "discounts": discounts,
                "count": len(discounts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )
