"""ShopifyCustomerSegmentsAdapter — read and create customer segments.

Shopify segments are dynamic customer cohorts defined by a filter
expression (the "ShopifyQL-like" segment query language). They power
email targeting, retention campaigns, churn outreach, and the
"customers who bought X but never came back" follow-up that ShopAI's
retention engine wants to automate.

ShopAI use cases:

  * **Read existing segments.** The retention / email engines list
    segments to know what cohorts the merchant has already defined
    (so they can target them rather than hand-rolling a duplicate).
  * **Enumerate members.** Pulling the customers in a segment is
    how the email engine actually addresses an outreach campaign.
  * **Create new segments.** When the churn engine identifies a
    new at-risk cohort ("hasn't ordered in 60 days, lifetime value
    > $200") it materialises that as a segment so the merchant
    can also see / hand-edit it from admin.

Capabilities:

  * ``SHOPIFY_QUERY_SEGMENT``       — list segments with optional
    name/query filter and pagination.
  * ``SHOPIFY_GET_SEGMENT_MEMBERS`` — page through customers in a
    specific segment.
  * ``SHOPIFY_CREATE_SEGMENT``      — define a new segment from a
    name + segment-language query.

Update / delete are intentionally out of scope until the retention
engine actually needs to mutate existing segments — most engines
treat segments as append-only.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_QUERY_SEGMENTS = """
query segments(
  $first: Int!, $after: String, $query: String,
  $sortKey: SegmentSortKeys, $reverse: Boolean
) {
  segments(
    first: $first, after: $after, query: $query,
    sortKey: $sortKey, reverse: $reverse
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        query
        creationDate
        lastEditDate
      }
    }
  }
}
""".strip()


# Note: ``SegmentStatistics`` does NOT expose a ``totalCount`` field
# in the current schema (caught live as 'Field totalCount doesn't
# exist on type SegmentStatistics'). The connection's pageInfo is
# sufficient signal for "are there more"; the total is computed by
# scanning the connection if a caller needs it.
_GET_SEGMENT_MEMBERS_QUERY = """
query customerSegmentMembers(
  $segmentId: ID!, $first: Int!, $after: String
) {
  customerSegmentMembers(
    segmentId: $segmentId, first: $first, after: $after
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        firstName
        lastName
        displayName
        defaultEmailAddress {
          emailAddress
        }
        defaultPhoneNumber {
          phoneNumber
        }
        amountSpent {
          amount
          currencyCode
        }
        numberOfOrders
      }
    }
  }
}
""".strip()


# segmentCreate uses Shopify's older ``UserError`` type which has no
# ``code`` field (Pattern F in CLAUDE.md, same as the orderEdit
# mutations). Drop ``code`` from the selection.
_CREATE_SEGMENT_MUTATION = """
mutation segmentCreate($name: String!, $query: String!) {
  segmentCreate(name: $name, query: $query) {
    segment {
      id
      name
      query
      creationDate
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyCustomerSegmentsAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_segments"
    capabilities = {
        Capability.SHOPIFY_QUERY_SEGMENT,
        Capability.SHOPIFY_GET_SEGMENT_MEMBERS,
        Capability.SHOPIFY_CREATE_SEGMENT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_QUERY_SEGMENT:
            return self._query_segments(params)
        if capability == Capability.SHOPIFY_GET_SEGMENT_MEMBERS:
            return self._get_segment_members(params)
        if capability == Capability.SHOPIFY_CREATE_SEGMENT:
            return self._create_segment(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Query (list) segments ─────────────────────────────────────

    def _query_segments(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'cursor' must be a string or None",
            )
        query = params.get("query") or params.get("filter")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'query' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_customer_segments",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))

        data = self._gql(_QUERY_SEGMENTS, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": reverse,
        })
        envelope = data.get("segments") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        segments: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            segments.append({
                "id": node.get("id", "") or "",
                "name": node.get("name", "") or "",
                "query": node.get("query", "") or "",
                "created_at": node.get("creationDate", "") or "",
                "updated_at": node.get("lastEditDate", "") or "",
            })
        return self._success(
            Capability.SHOPIFY_QUERY_SEGMENT,
            data={
                "segments": segments,
                "count": len(segments),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get segment members ───────────────────────────────────────

    def _get_segment_members(self, params: dict[str, Any]) -> Any:
        segment_id = params.get("segment_id") or params.get("segmentId")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'segment_id' (Shopify GID for the segment) is required",
            )

        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'cursor' must be a string or None",
            )

        data = self._gql(_GET_SEGMENT_MEMBERS_QUERY, {
            "segmentId": segment_id.strip(),
            "first": limit,
            "after": cursor,
        })
        envelope = data.get("customerSegmentMembers") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        members = [
            self._normalise_member(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_GET_SEGMENT_MEMBERS,
            data={
                "segment_id": segment_id.strip(),
                "members": members,
                "count": len(members),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create segment ────────────────────────────────────────────

    def _create_segment(self, params: dict[str, Any]) -> Any:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'name' is required (non-empty string)",
            )
        query = params.get("query") or params.get("filter")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                "shopify_customer_segments",
                "'query' is required (the segment's filter expression, "
                "e.g. \"customer_lifetime_value > 200 AND "
                "last_order_date < -60d\")",
            )

        data = self._gql(_CREATE_SEGMENT_MUTATION, {
            "name": name.strip(),
            "query": query.strip(),
        })
        self._check_user_errors(data, "segmentCreate")
        payload = data.get("segmentCreate") or {}
        seg = payload.get("segment") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_SEGMENT,
            data={
                "segment": {
                    "id": seg.get("id", "") or "",
                    "name": seg.get("name", "") or "",
                    "query": seg.get("query", "") or "",
                    "created_at": seg.get("creationDate", "") or "",
                },
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_member(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        email = node.get("defaultEmailAddress") or {}
        phone = node.get("defaultPhoneNumber") or {}
        spent = node.get("amountSpent") or {}
        try:
            amount = float(spent.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "id": node.get("id", "") or "",
            "first_name": node.get("firstName", "") or "",
            "last_name": node.get("lastName", "") or "",
            "display_name": node.get("displayName", "") or "",
            "email": (
                email.get("emailAddress", "") if isinstance(email, dict) else ""
            ) or "",
            "phone": (
                phone.get("phoneNumber", "") if isinstance(phone, dict) else ""
            ) or "",
            "amount_spent": amount,
            "currency": spent.get("currencyCode", "") or "",
            "orders_count": int(node.get("numberOfOrders", 0) or 0),
        }
