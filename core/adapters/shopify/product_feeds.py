"""ShopifyProductFeedsAdapter — sales-channel product feed management.

A "product feed" in Shopify is a per-(language, country) catalogue
slice an external sales channel (Google Shopping, Meta catalog,
TikTok Shop, etc.) reads from. The merchant publishes a feed for
every market+language pair they want to sell into; downstream
channels poll the feed to keep their own product listings in sync.

ShopAI's sales-channel + internationalization engines write these:

  * Spin up a new feed when the merchant unlocks a market
    (e.g. shop expanded into FR-CA — create the corresponding
    fr-FR-CA feed).
  * Trigger a FULL SYNC after a bulk price/availability change
    so downstream channels don't lag (Shopify normally pushes
    incremental deltas; full-sync forces a complete refresh).
  * Retire a feed when a market is being decommissioned.

Capabilities:

  * ``SHOPIFY_LIST_PRODUCT_FEEDS``        — paginated list.
  * ``SHOPIFY_GET_PRODUCT_FEED``          — single feed by GID.
  * ``SHOPIFY_CREATE_PRODUCT_FEED``       — productFeedCreate.
    Pattern A: input wrapper with language + country codes.
  * ``SHOPIFY_DELETE_PRODUCT_FEED``       — productFeedDelete.
  * ``SHOPIFY_TRIGGER_PRODUCT_FULL_SYNC`` — productFullSync.
    Optional ``beforeUpdatedAt`` / ``updatedAtSince`` to scope the
    re-emission to a date window.

Friendly call shape (create)::

    {"language": "fr",   # ISO 639-1 lowercased
     "country":  "CA"}   # ISO 3166-1 alpha-2 uppercased

Friendly call shape (full-sync)::

    {"id":                "gid://shopify/ProductFeed/123",
     "before_updated_at": "2026-04-01T00:00:00Z",  # optional
     "updated_at_since":  "2026-03-01T00:00:00Z"}  # optional

Pattern A — id at field level (delete + full-sync); create uses
the standard ``input`` wrapper.
Pattern F — all three mutation userError types
(ProductFeedCreateUserError, ProductFeedDeleteUserError,
ProductFullSyncUserError) carry the ``code`` field.

Pattern E note: gated by ``read_product_listings`` /
``write_product_listings`` (or a sales-channel-app-specific scope).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FEED_FIELDS = """
id
language
country
status
""".strip()


_LIST_QUERY = f"""
query productFeeds(
  $first: Int!,
  $after: String,
  $reverse: Boolean
) {{
  productFeeds(
    first: $first, after: $after, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_FEED_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_QUERY = f"""
query productFeed($id: ID!) {{
  productFeed(id: $id) {{
    {_FEED_FIELDS}
  }}
}}
""".strip()


_CREATE_MUTATION = f"""
mutation productFeedCreate($input: ProductFeedInput!) {{
  productFeedCreate(input: $input) {{
    productFeed {{
      {_FEED_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_MUTATION = """
mutation productFeedDelete($id: ID!) {
  productFeedDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_FULL_SYNC_MUTATION = """
mutation productFullSync(
  $id: ID!,
  $beforeUpdatedAt: DateTime,
  $updatedAtSince: DateTime
) {
  productFullSync(
    id: $id,
    beforeUpdatedAt: $beforeUpdatedAt,
    updatedAtSince: $updatedAtSince
  ) {
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


class ShopifyProductFeedsAdapter(ShopifyBaseAdapter):
    name = "shopify_product_feeds"
    capabilities = {
        Capability.SHOPIFY_LIST_PRODUCT_FEEDS,
        Capability.SHOPIFY_GET_PRODUCT_FEED,
        Capability.SHOPIFY_CREATE_PRODUCT_FEED,
        Capability.SHOPIFY_DELETE_PRODUCT_FEED,
        Capability.SHOPIFY_TRIGGER_PRODUCT_FULL_SYNC,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PRODUCT_FEEDS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_PRODUCT_FEED:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_PRODUCT_FEED:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_PRODUCT_FEED:
            return self._delete(params)
        if capability == Capability.SHOPIFY_TRIGGER_PRODUCT_FULL_SYNC:
            return self._full_sync(params)
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

        reverse = params.get("reverse")
        data = self._gql(_LIST_QUERY, {
            "first": limit,
            "after": cursor,
            "reverse": bool(reverse) if reverse is not None else None,
        })
        envelope = data.get("productFeeds") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        feeds = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PRODUCT_FEEDS,
            data={
                "feeds": feeds,
                "count": len(feeds),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        feed_id = self._extract_id(params)
        data = self._gql(_GET_QUERY, {"id": feed_id})
        node = data.get("productFeed") or {}
        return self._success(
            Capability.SHOPIFY_GET_PRODUCT_FEED,
            data={
                "feed": self._normalise(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        language = params.get("language") or params.get("language_code")
        country = (
            params.get("country")
            or params.get("country_code")
            or params.get("countryCode")
        )
        if not isinstance(language, str) or not language.strip():
            raise AdapterValidationError(
                self.name,
                "'language' is required (ISO 639-1 code, e.g. 'fr', "
                "'es', 'de')",
            )
        if not isinstance(country, str) or not country.strip():
            raise AdapterValidationError(
                self.name,
                "'country' is required (ISO 3166-1 alpha-2 code, "
                "e.g. 'US', 'CA', 'DE')",
            )

        body = {
            "language": language.strip().upper(),
            "country": country.strip().upper(),
        }
        data = self._gql(_CREATE_MUTATION, {"input": body})
        self._check_user_errors(data, "productFeedCreate")
        payload = data.get("productFeedCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PRODUCT_FEED,
            data={
                "feed": self._normalise(
                    payload.get("productFeed") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        feed_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {"id": feed_id})
        self._check_user_errors(data, "productFeedDelete")
        payload = data.get("productFeedDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PRODUCT_FEED,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Full sync ──────────────────────────────────────────────────

    def _full_sync(self, params: dict[str, Any]) -> Any:
        feed_id = self._extract_id(params)
        before = (
            params.get("before_updated_at")
            or params.get("beforeUpdatedAt")
        )
        since = (
            params.get("updated_at_since")
            or params.get("updatedAtSince")
        )
        if before is not None and not isinstance(before, str):
            raise AdapterValidationError(
                self.name,
                "'before_updated_at' must be an ISO datetime string",
            )
        if since is not None and not isinstance(since, str):
            raise AdapterValidationError(
                self.name,
                "'updated_at_since' must be an ISO datetime string",
            )

        data = self._gql(_FULL_SYNC_MUTATION, {
            "id": feed_id,
            "beforeUpdatedAt": (
                before.strip() if isinstance(before, str)
                and before.strip() else None
            ),
            "updatedAtSince": (
                since.strip() if isinstance(since, str)
                and since.strip() else None
            ),
        })
        self._check_user_errors(data, "productFullSync")
        return self._success(
            Capability.SHOPIFY_TRIGGER_PRODUCT_FULL_SYNC,
            data={
                "feed_id": feed_id,
                "before_updated_at": before or "",
                "updated_at_since": since or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        feed_id = (
            params.get("id")
            or params.get("feed_id")
            or params.get("product_feed_id")
            or params.get("productFeedId")
        )
        if not isinstance(feed_id, str) or not feed_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the product feed) is required",
            )
        return feed_id.strip()

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "language": node.get("language", "") or "",
            "country": node.get("country", "") or "",
            "status": node.get("status", "") or "",
        }
