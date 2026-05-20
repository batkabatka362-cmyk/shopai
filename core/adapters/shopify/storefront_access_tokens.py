"""ShopifyStorefrontAccessTokensAdapter — Storefront API token CRUD.

Storefront access tokens grant a *third party* (the merchant's headless
front-end, a custom mobile app, a sales-channel integration) read
access to the shop's catalog through the Storefront GraphQL API
(distinct from the Admin API the rest of these adapters wrap).
A long-lived token is minted per consumer with a human-readable
title, and revoked by id when the consumer is decommissioned.

ShopAI's headless-storefront engine uses these to:

  * Mint a fresh token when an operator wires up a new headless
    site or mobile app and needs a clean credential to ship.
  * Audit the token list (which titles? when minted?) before a
    security review.
  * Revoke leaked or stale tokens identified during the audit.

Capabilities:

  * ``SHOPIFY_LIST_STOREFRONT_ACCESS_TOKENS``  — paginated list
    via ``Shop.storefrontAccessTokens`` (Pattern B — no top-level
    Query.storefrontAccessTokens connection).
  * ``SHOPIFY_CREATE_STOREFRONT_ACCESS_TOKEN`` —
    storefrontAccessTokenCreate. Title required. Returns the
    secret token bytes — surface them once (post-create) and
    expect the operator to copy them somewhere durable; Shopify
    won't expose the value again on subsequent reads.
  * ``SHOPIFY_DELETE_STOREFRONT_ACCESS_TOKEN`` —
    storefrontAccessTokenDelete. Id at field level inside
    StorefrontAccessTokenDeleteInput.

Pattern B confirmed via introspection: ``QueryRoot`` has no
``storefrontAccessTokens`` field; the connection lives on
``Shop``.

Pattern F: both mutations use the bare ``UserError`` type
(no ``code`` field — probed live: GraphQL rejects ``code`` in the
selection). Drop ``code`` per Pattern F.

Pattern E note: gated by ``write_storefront_access_tokens`` for
mutations; reads need ``read_storefront_access_tokens``. Note this
scope is sometimes also gated by Partner App Store registration —
custom-installed apps may receive ACCESS_DENIED.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_TOKEN_FIELDS = """
id
accessToken
title
accessScopes {
  handle
}
createdAt
updatedAt
""".strip()


_LIST_QUERY = f"""
query shopStorefrontAccessTokens(
  $first: Int!,
  $after: String,
  $reverse: Boolean
) {{
  shop {{
    storefrontAccessTokens(
      first: $first, after: $after, reverse: $reverse
    ) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_TOKEN_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_CREATE_MUTATION = f"""
mutation storefrontAccessTokenCreate(
  $input: StorefrontAccessTokenInput!
) {{
  storefrontAccessTokenCreate(input: $input) {{
    storefrontAccessToken {{
      {_TOKEN_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_MUTATION = """
mutation storefrontAccessTokenDelete(
  $input: StorefrontAccessTokenDeleteInput!
) {
  storefrontAccessTokenDelete(input: $input) {
    deletedStorefrontAccessTokenId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyStorefrontAccessTokensAdapter(ShopifyBaseAdapter):
    name = "shopify_storefront_access_tokens"
    capabilities = {
        Capability.SHOPIFY_LIST_STOREFRONT_ACCESS_TOKENS,
        Capability.SHOPIFY_CREATE_STOREFRONT_ACCESS_TOKEN,
        Capability.SHOPIFY_DELETE_STOREFRONT_ACCESS_TOKEN,
    }
    # Shopify removed the dedicated ``read_storefront_tokens`` /
    # ``write_storefront_tokens`` scopes in 2026+ (no longer in
    # the Partners Dashboard scope selector; including them in an
    # install URL causes Shopify to silently reject the request).
    # The storefrontAccessToken CRUD mutations are still callable
    # without a dedicated scope -- treat the adapter as
    # scope_independent, same shape as webhooks / shop / bulk.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_STOREFRONT_ACCESS_TOKENS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_STOREFRONT_ACCESS_TOKEN:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_STOREFRONT_ACCESS_TOKEN:
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

        reverse = params.get("reverse")

        data = self._gql(_LIST_QUERY, {
            "first": limit,
            "after": cursor,
            "reverse": bool(reverse) if reverse is not None else None,
        })
        shop = data.get("shop") or {}
        envelope = shop.get("storefrontAccessTokens") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        tokens = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_STOREFRONT_ACCESS_TOKENS,
            data={
                "access_tokens": tokens,
                "count": len(tokens),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name,
                "'title' is required (the human-readable token "
                "label — used to identify which consumer the token "
                "was minted for)",
            )
        data = self._gql(_CREATE_MUTATION, {
            "input": {"title": title.strip()},
        })
        self._check_user_errors(data, "storefrontAccessTokenCreate")
        payload = data.get("storefrontAccessTokenCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_STOREFRONT_ACCESS_TOKEN,
            data={
                "access_token": self._normalise(
                    payload.get("storefrontAccessToken") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        token_id = (
            params.get("id")
            or params.get("token_id")
            or params.get("storefront_access_token_id")
            or params.get("storefrontAccessTokenId")
        )
        if not isinstance(token_id, str) or not token_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the storefront access token) "
                "is required",
            )
        data = self._gql(_DELETE_MUTATION, {
            "input": {"id": token_id.strip()},
        })
        self._check_user_errors(data, "storefrontAccessTokenDelete")
        payload = data.get("storefrontAccessTokenDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_STOREFRONT_ACCESS_TOKEN,
            data={
                "deleted_id": (
                    payload.get("deletedStorefrontAccessTokenId", "")
                    or ""
                ),
            },
        )

    # ── Normalisation ─────────────────────────────────────────────

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        scopes_raw = node.get("accessScopes") or []
        scope_handles = []
        for s in scopes_raw:
            if isinstance(s, dict):
                handle = s.get("handle")
                if isinstance(handle, str) and handle:
                    scope_handles.append(handle)
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "access_token": node.get("accessToken", "") or "",
            "access_scopes": scope_handles,
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
