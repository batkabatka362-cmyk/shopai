"""ShopifyChannelsAdapter — read installed sales channels.

Channels are the *integration apps* connected to a shop's sales
surface — Online Store, Shop App, Facebook & Instagram, Google,
TikTok, Point of Sale, etc. They differ from publications:

  * **Publications** (handled by ``ShopifyPublicationsAdapter``) are
    *publish targets* — what's visible where. Each sales channel
    typically owns one publication, but a channel can register
    multiple, and the publishing surface is per-publication.
  * **Channels** are the *integration metadata* — which apps are
    connected, what handle they use, how recently they last synced.

Why ShopAI engines want channels visibility:

  * **Multi-channel listing engine** lists channels to know what
    apps to push winning products through. The publications adapter
    handles the publish itself; channels tells you what *is* a
    channel in the first place.
  * **Compliance / audit** flows want to know which third-party
    apps have read access to the storefront — the channels list
    is the inventory.

Capability (read-only):

  * ``SHOPIFY_LIST_CHANNELS`` — paginate channels with cursor.

No create / update / delete: channels are installed as Shopify
apps via the App Store flow, not provisioned through API. Engines
that want to add a channel must point the merchant at the App
Store install link (out of scope for this adapter).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_LIST_CHANNELS_QUERY = """
query channels($first: Int!, $after: String) {
  channels(first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        handle
        supportsFuturePublishing
      }
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyChannelsAdapter(ShopifyBaseAdapter):
    name = "shopify_channels"
    capabilities = {
        Capability.SHOPIFY_LIST_CHANNELS,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_LIST_CHANNELS:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return self._list(params)

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
                "shopify_channels", "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_CHANNELS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("channels") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        channels: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            channels.append({
                "id": node.get("id", "") or "",
                "name": node.get("name", "") or "",
                "handle": node.get("handle", "") or "",
                "supports_future_publishing": bool(
                    node.get("supportsFuturePublishing", False)
                ),
            })
        return self._success(
            Capability.SHOPIFY_LIST_CHANNELS,
            data={
                "channels": channels,
                "count": len(channels),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )
