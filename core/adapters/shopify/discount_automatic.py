"""ShopifyDiscountAutomaticAdapter — automatic (no-code) discounts.

Companion to ``discounts.py`` (which manages CODE-based discounts —
the customer types "WELCOME15" at checkout). Automatic discounts
apply WITHOUT a code: the customer adds 3 items to the cart and the
"Buy 3 get 10% off" rule kicks in silently.

ShopAI's pricing engine + merchandising engine use these for:

  * Site-wide promotional pushes ("everything 15% off this weekend")
  * BOGO / bundle offers driven by cart contents
  * Customer-segment perks ("VIP customers always get free shipping")

Capabilities:

  * ``SHOPIFY_LIST_AUTOMATIC_DISCOUNTS``  — list active automatic
    discounts (filter by status, sort by start time).
  * ``SHOPIFY_CREATE_AUTOMATIC_DISCOUNT`` — create a percentage-off
    automatic discount.
  * ``SHOPIFY_DELETE_AUTOMATIC_DISCOUNT`` — delete by GID.

Friendly create call shape (mirrors discounts.py for consistency)::

    {"title":         "Site-wide 15% off",
     "percentage":    15,
     "starts_at":     "2026-04-26T00:00:00Z",
     "ends_at":       "2026-04-30T23:59:59Z",
     "minimum_subtotal": "50.00",
     "applies_to":    "ALL"}                  # or "PRODUCTS" / "COLLECTIONS"

Pattern A note: discountAutomaticBasicCreate takes a single
``automaticBasicDiscount`` argument (named after the input type, not
generic "input"). Same Pattern A as discounts.py, marketing_events,
validations.

Pattern B note: ``Query.automaticDiscountNodes`` exists; it returns
DiscountAutomaticNode wrappers around the underlying typed nodes
(DiscountAutomaticBasic / Bxgy / FreeShipping). The adapter
flattens via inline fragments so engines see one unified shape.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_AUTOMATIC_NODE_FIELDS = """
id
automaticDiscount {
  __typename
  ... on DiscountAutomaticBasic {
    title
    summary
    status
    startsAt
    endsAt
    asyncUsageCount
    minimumRequirement {
      __typename
      ... on DiscountMinimumQuantity {
        greaterThanOrEqualToQuantity
      }
      ... on DiscountMinimumSubtotal {
        greaterThanOrEqualToSubtotal {
          amount
          currencyCode
        }
      }
    }
    customerGets {
      value {
        __typename
        ... on DiscountPercentage {
          percentage
        }
        ... on DiscountAmount {
          amount {
            amount
            currencyCode
          }
          appliesOnEachItem
        }
      }
      items {
        __typename
        ... on AllDiscountItems {
          allItems
        }
      }
    }
  }
  ... on DiscountAutomaticBxgy {
    title
    summary
    status
    startsAt
    endsAt
    asyncUsageCount
  }
  ... on DiscountAutomaticFreeShipping {
    title
    summary
    status
    startsAt
    endsAt
    asyncUsageCount
  }
}
""".strip()


_LIST_AUTOMATIC_DISCOUNTS_QUERY = f"""
query automaticDiscountNodes(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: AutomaticDiscountSortKeys,
  $reverse: Boolean
) {{
  automaticDiscountNodes(
    first: $first,
    after: $after,
    query: $query,
    sortKey: $sortKey,
    reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_AUTOMATIC_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_AUTOMATIC_BASIC_MUTATION = """
mutation discountAutomaticBasicCreate(
  $automaticBasicDiscount: DiscountAutomaticBasicInput!
) {
  discountAutomaticBasicCreate(
    automaticBasicDiscount: $automaticBasicDiscount
  ) {
    automaticDiscountNode {
      id
      automaticDiscount {
        ... on DiscountAutomaticBasic {
          title
          status
          startsAt
          endsAt
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


_DELETE_AUTOMATIC_DISCOUNT_MUTATION = """
mutation discountAutomaticDelete($id: ID!) {
  discountAutomaticDelete(id: $id) {
    deletedAutomaticDiscountId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

# Pattern D: AutomaticDiscountSortKeys is a NARROW enum — only
# CREATED_AT and ID. The broader sort keys that other connections
# accept (TITLE, STARTS_AT, RELEVANCE, ...) all reject here.
_VALID_SORT_KEYS = {"CREATED_AT", "ID"}

_VALID_APPLIES_TO = {"ALL"}  # ALL is the only flat target the basic mutation handles
                              # — for COLLECTIONS / PRODUCTS the Bxgy mutation
                              # provides the dedicated input shape.


class ShopifyDiscountAutomaticAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_automatic"
    capabilities = {
        Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS,
        Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT,
        Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        sort_key = params.get("sort_key")
        if sort_key is not None:
            if not isinstance(sort_key, str) or sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_AUTOMATIC_DISCOUNTS_QUERY, variables)
        envelope = data.get("automaticDiscountNodes") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        discounts = [
            self._normalise_discount(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS,
            data={
                "discounts": discounts,
                "count": len(discounts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        discount_input = self._build_basic_input(params)
        data = self._gql(_CREATE_AUTOMATIC_BASIC_MUTATION, {
            "automaticBasicDiscount": discount_input,
        })
        self._check_user_errors(data, "discountAutomaticBasicCreate")
        payload = data.get("discountAutomaticBasicCreate") or {}
        node = payload.get("automaticDiscountNode") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT,
            data={
                "discount": self._normalise_discount(node),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        discount_id = params.get("id") or params.get("discount_id")
        if not isinstance(discount_id, str) or not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the automatic discount node) is required",
            )
        data = self._gql(_DELETE_AUTOMATIC_DISCOUNT_MUTATION, {
            "id": discount_id.strip(),
        })
        self._check_user_errors(data, "discountAutomaticDelete")
        payload = data.get("discountAutomaticDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT,
            data={
                "deleted_id": (
                    payload.get("deletedAutomaticDiscountId", "") or ""
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_basic_input(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name, "'title' is required",
            )

        starts_at = params.get("starts_at") or params.get("startsAt")
        if not isinstance(starts_at, str) or not starts_at.strip():
            raise AdapterValidationError(
                self.name,
                "'starts_at' is required (ISO-8601, e.g. "
                "'2026-04-26T00:00:00Z')",
            )

        out: dict[str, Any] = {
            "title": title.strip(),
            "startsAt": starts_at.strip(),
        }

        ends_at = params.get("ends_at") or params.get("endsAt")
        if ends_at is not None:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    self.name, "'ends_at' must be a string",
                )
            out["endsAt"] = ends_at.strip()

        # customerGets value: percentage takes precedence over amount.
        percentage = params.get("percentage")
        amount_off = params.get("amount_off") or params.get("amountOff")
        if percentage is not None:
            try:
                pct_float = float(percentage)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'percentage' must be numeric",
                ) from exc
            if pct_float < 0 or pct_float > 100:
                raise AdapterValidationError(
                    self.name,
                    "'percentage' must be between 0 and 100",
                )
            customer_value = {"percentage": pct_float / 100.0}
        elif amount_off is not None:
            try:
                amount_float = float(amount_off)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'amount_off' must be numeric",
                ) from exc
            if amount_float <= 0:
                raise AdapterValidationError(
                    self.name, "'amount_off' must be positive",
                )
            customer_value = {
                "discountAmount": {
                    "amount": amount_float,
                    "appliesOnEachItem": bool(
                        params.get("applies_on_each_item", False),
                    ),
                },
            }
        else:
            raise AdapterValidationError(
                self.name,
                "either 'percentage' (0-100) or 'amount_off' is required",
            )

        applies_to = params.get("applies_to") or "ALL"
        if not isinstance(applies_to, str) or applies_to.upper() not in _VALID_APPLIES_TO:
            raise AdapterValidationError(
                self.name,
                f"'applies_to' must be one of: {sorted(_VALID_APPLIES_TO)} "
                "(use the Bxgy mutation for product/collection targets)",
            )

        out["customerGets"] = {
            "value": customer_value,
            "items": {"all": True},
        }

        # Minimum requirement (subtotal or quantity).
        minimum_subtotal = params.get("minimum_subtotal")
        minimum_quantity = params.get("minimum_quantity")
        if minimum_subtotal is not None and minimum_quantity is not None:
            raise AdapterValidationError(
                self.name,
                "specify only one of 'minimum_subtotal' / 'minimum_quantity'",
            )
        if minimum_subtotal is not None:
            try:
                subtotal_float = float(minimum_subtotal)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'minimum_subtotal' must be numeric",
                ) from exc
            out["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": subtotal_float,
                },
            }
        elif minimum_quantity is not None:
            try:
                qty_int = int(minimum_quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'minimum_quantity' must be a positive integer",
                ) from exc
            if qty_int < 1:
                raise AdapterValidationError(
                    self.name,
                    "'minimum_quantity' must be a positive integer",
                )
            out["minimumRequirement"] = {
                "quantity": {
                    "greaterThanOrEqualToQuantity": str(qty_int),
                },
            }

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @classmethod
    def _normalise_discount(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        discount = node.get("automaticDiscount") or {}
        if not isinstance(discount, dict):
            discount = {}
        kind = discount.get("__typename", "") or ""

        out = {
            "id": node.get("id", "") or "",
            "kind": kind,
            "title": discount.get("title", "") or "",
            "summary": discount.get("summary", "") or "",
            "status": discount.get("status", "") or "",
            "starts_at": discount.get("startsAt", "") or "",
            "ends_at": discount.get("endsAt", "") or "",
            "usage_count": int(discount.get("asyncUsageCount") or 0),
        }

        if kind == "DiscountAutomaticBasic":
            customer_gets = discount.get("customerGets") or {}
            value = (
                customer_gets.get("value", {})
                if isinstance(customer_gets, dict) else {}
            ) or {}
            value_kind = (
                value.get("__typename", "")
                if isinstance(value, dict) else ""
            ) or ""
            if value_kind == "DiscountPercentage":
                # Shopify percentages are 0-1 fractions; surface as 0-100.
                pct = value.get("percentage", 0) if isinstance(value, dict) else 0
                try:
                    out["percentage"] = float(pct or 0) * 100.0
                except (TypeError, ValueError):
                    out["percentage"] = 0.0
            elif value_kind == "DiscountAmount":
                amount = (
                    value.get("amount", {}) if isinstance(value, dict) else {}
                ) or {}
                out["amount_off"] = (
                    amount.get("amount", "")
                    if isinstance(amount, dict) else ""
                ) or ""
                out["amount_currency"] = (
                    amount.get("currencyCode", "")
                    if isinstance(amount, dict) else ""
                ) or ""

            min_req = discount.get("minimumRequirement") or {}
            min_kind = (
                min_req.get("__typename", "")
                if isinstance(min_req, dict) else ""
            ) or ""
            if min_kind == "DiscountMinimumSubtotal":
                subtotal = (
                    min_req.get("greaterThanOrEqualToSubtotal", {})
                    if isinstance(min_req, dict) else {}
                ) or {}
                out["minimum_subtotal"] = (
                    subtotal.get("amount", "")
                    if isinstance(subtotal, dict) else ""
                ) or ""
            elif min_kind == "DiscountMinimumQuantity":
                out["minimum_quantity"] = int(
                    (min_req.get("greaterThanOrEqualToQuantity") or 0)
                    if isinstance(min_req, dict) else 0
                )

        return out
