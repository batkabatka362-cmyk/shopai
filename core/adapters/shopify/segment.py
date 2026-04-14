"""ShopifySegmentAdapter — query customer segments.

Fills the ``SHOPIFY_QUERY_SEGMENT`` gap in the adapter catalog
(Option D). Customer segments are Shopify's saved-query primitive
used by marketing flows: the segment UI evaluates a query like
``tag = "vip" AND orders_count > 5`` and stores the result set
so downstream tools (Shopify Email, Flow, Launchpad) can target
the slice without re-running the expensive filter.

Two access modes:

  * **List existing segments** — ``{"mode": "list"}`` returns the
    saved segments with id/name/query/last_edit.
  * **Evaluate a query inline** — ``{"mode": "preview", "query":
    "tag:'vip' AND orders_count > 5"}`` returns the customer
    count matching the predicate without saving a segment.
    Useful for "how big is the audience before I spend money
    targeting it" flows.

Params shape (mode=list)::

    {"mode": "list", "first": 25, "after": "cursor..."}

Params shape (mode=preview)::

    {"mode": "preview", "query": "tag:'vip' AND orders_count > 5"}

Returns (list)::

    {
        "segments": [
            {"id": "gid://...", "name": "VIPs", "query": "...", "last_edit_date": "..."},
            ...
        ],
        "page_info": {"has_next_page": bool, "end_cursor": str},
        "count": int,
    }

Returns (preview)::

    {
        "query":  "tag:'vip' ...",
        "count":  1234,
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_LIST_SEGMENTS_QUERY = """
query ListSegments($first: Int!, $after: String) {
  segments(first: $first, after: $after, sortKey: LAST_EDIT_DATE, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id
        name
        query
        lastEditDate
        creationDate
      }
    }
  }
}
""".strip()


_PREVIEW_SEGMENT_QUERY = """
query PreviewSegment($query: String!) {
  customerSegmentMembers(query: $query, first: 1) {
    statistics { totalCount }
  }
}
""".strip()


_ALLOWED_MODES = {"list", "preview"}


class ShopifySegmentAdapter(ShopifyBaseAdapter):
    """Query Shopify customer segments."""

    name = "shopify_segment"
    capabilities = {Capability.SHOPIFY_QUERY_SEGMENT}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_QUERY_SEGMENT:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        mode = str(params.get("mode") or "list").lower()
        if mode not in _ALLOWED_MODES:
            raise AdapterValidationError(
                self.name,
                f"'mode' must be one of {sorted(_ALLOWED_MODES)}",
            )

        if mode == "list":
            return self._list(params)
        return self._preview(params)

    # ── list ─────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        try:
            first = int(params.get("first", 25))
        except (TypeError, ValueError):
            raise AdapterValidationError(
                self.name, "'first' must be an integer",
            )
        if first <= 0 or first > 250:
            raise AdapterValidationError(
                self.name, "'first' must be in 1..250 (Shopify cap)",
            )
        after = params.get("after")

        data = self._gql(
            _LIST_SEGMENTS_QUERY,
            {"first": first, "after": after or None},
        )
        block = data.get("segments") or {}
        edges = block.get("edges") or []
        page_info = block.get("pageInfo") or {}

        out: list[dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            out.append({
                "id": node.get("id", ""),
                "name": node.get("name", "") or "",
                "query": node.get("query", "") or "",
                "last_edit_date": node.get("lastEditDate", "") or "",
                "creation_date": node.get("creationDate", "") or "",
                "cursor": edge.get("cursor", ""),
            })

        return self._success(
            Capability.SHOPIFY_QUERY_SEGMENT,
            data={
                "mode": "list",
                "segments": out,
                "count": len(out),
                "page_info": {
                    "has_next_page": bool(page_info.get("hasNextPage")),
                    "end_cursor": page_info.get("endCursor", "") or "",
                },
            },
        )

    # ── preview ──────────────────────────────────────────────

    def _preview(self, params: dict[str, Any]) -> Any:
        query = str(params.get("query") or "").strip()
        if not query:
            raise AdapterValidationError(
                self.name, "'query' is required for mode=preview",
            )

        data = self._gql(_PREVIEW_SEGMENT_QUERY, {"query": query})
        members = data.get("customerSegmentMembers") or {}
        stats = members.get("statistics") or {}
        total = int(stats.get("totalCount", 0) or 0)

        return self._success(
            Capability.SHOPIFY_QUERY_SEGMENT,
            data={
                "mode": "preview",
                "query": query,
                "count": total,
            },
        )
