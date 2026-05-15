"""ShopifyPublicationsAdapter — multi-channel publishing.

Shopify exposes "publications" — sales channels like Online Store,
Shop App, Facebook & Instagram, Google, TikTok, etc. Each product or
collection has to be explicitly published to a channel before it
appears there. Without an adapter, ShopAI's "winning products → push
to all channels" workflow has to be done by hand in the merchant's
admin.

Two flows ShopAI engines need:

  * **Auto-publish winning products.** When the winning-products
    engine validates a product (volume, ROAS, margin), the engine
    pushes it to every configured channel so the merchant doesn't
    have to remember to publish manually.
  * **Auto-unpublish underperformers.** When ROAS guardrails kill
    a SKU, the engine should also pull it from secondary channels
    (FB/IG/etc.) so the merchant doesn't keep paying ad delivery
    on stock that's not converting.

Capabilities:

  * ``SHOPIFY_LIST_PUBLICATIONS`` — list channels available on the
    shop (Shop, Online Store, Shop Channel App, etc.). Drives
    "publish to all channels" by enumerating targets.
  * ``SHOPIFY_PUBLISH_RESOURCE`` — publish a product/collection to
    1..N channels via ``publishablePublish``.
  * ``SHOPIFY_UNPUBLISH_RESOURCE`` — remove from 1..N channels via
    ``publishableUnpublish``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_LIST_PUBLICATIONS_QUERY = """
query publications($first: Int!) {
  publications(first: $first) {
    edges {
      node {
        id
        name
        supportsFuturePublishing
      }
    }
  }
}
""".strip()


# Common selection set for publishablePublish / publishableUnpublish.
# The publishable type is a union over Product / Collection /
# Publication; we destructure the union with __typename so the
# normaliser knows which kind it just operated on.
_PUBLISHABLE_FIELDS = """
publishable {
  __typename
  ... on Product {
    id
    title
    publishedOnPublication: publishedOnPublication(publicationId: $publicationId)
  }
  ... on Collection {
    id
    title
    publishedOnPublication: publishedOnPublication(publicationId: $publicationId)
  }
}
""".strip()


_PUBLISH_MUTATION = """
mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    publishable {
      __typename
      ... on Product { id title }
      ... on Collection { id title }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_UNPUBLISH_MUTATION = """
mutation publishableUnpublish($id: ID!, $input: [PublicationInput!]!) {
  publishableUnpublish(id: $id, input: $input) {
    publishable {
      __typename
      ... on Product { id title }
      ... on Collection { id title }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
# Shopify caps publications query at 250.
_MAX_LIST_LIMIT = 250


class ShopifyPublicationsAdapter(ShopifyBaseAdapter):
    name = "shopify_publications"
    capabilities = {
        Capability.SHOPIFY_LIST_PUBLICATIONS,
        Capability.SHOPIFY_PUBLISH_RESOURCE,
        Capability.SHOPIFY_UNPUBLISH_RESOURCE,
    }
    # Publications ride on the product publication API.
    required_scopes = frozenset({
        "read_publications", "write_publications",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PUBLICATIONS:
            return self._list_publications(params)
        if capability == Capability.SHOPIFY_PUBLISH_RESOURCE:
            return self._publish(params, mutation=_PUBLISH_MUTATION,
                                 mutation_name="publishablePublish",
                                 capability=Capability.SHOPIFY_PUBLISH_RESOURCE)
        if capability == Capability.SHOPIFY_UNPUBLISH_RESOURCE:
            return self._publish(params, mutation=_UNPUBLISH_MUTATION,
                                 mutation_name="publishableUnpublish",
                                 capability=Capability.SHOPIFY_UNPUBLISH_RESOURCE)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list_publications(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        data = self._gql(_LIST_PUBLICATIONS_QUERY, {"first": limit})
        envelope = data.get("publications") or {}
        edges = envelope.get("edges") or []
        publications: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            publications.append({
                "id": node.get("id", "") or "",
                "name": node.get("name", "") or "",
                "supports_future_publishing": bool(
                    node.get("supportsFuturePublishing", False)
                ),
            })
        return self._success(
            Capability.SHOPIFY_LIST_PUBLICATIONS,
            data={
                "publications": publications,
                "count": len(publications),
            },
        )

    # ── Publish / Unpublish (shared shape) ─────────────────────────

    def _publish(
        self,
        params: dict[str, Any],
        *,
        mutation: str,
        mutation_name: str,
        capability: Capability,
    ) -> Any:
        resource_id = params.get("id") or params.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AdapterValidationError(
                "shopify_publications",
                "'id' (Shopify GID for the product or collection) "
                "is required",
            )

        # Accept either a single publication id or a list. Engines
        # often want to push to ALL channels at once — passing the
        # output of list_publications directly is idiomatic.
        publication_ids = (
            params.get("publication_ids")
            or params.get("publication_id")
        )
        if publication_ids is None:
            raise AdapterValidationError(
                "shopify_publications",
                "'publication_ids' (list) or 'publication_id' (single) "
                "is required",
            )
        if isinstance(publication_ids, str):
            publication_ids = [publication_ids]
        if not isinstance(publication_ids, list) or not publication_ids:
            raise AdapterValidationError(
                "shopify_publications",
                "'publication_ids' must be a non-empty list of GIDs",
            )

        publish_input: list[dict[str, Any]] = []
        for i, pub_id in enumerate(publication_ids):
            if not isinstance(pub_id, str) or not pub_id.strip():
                raise AdapterValidationError(
                    "shopify_publications",
                    f"publication_ids[{i}] must be a non-empty string GID",
                )
            publish_input.append({"publicationId": pub_id.strip()})

        data = self._gql(mutation, {
            "id": resource_id.strip(),
            "input": publish_input,
        })
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        publishable = payload.get("publishable") or {}
        return self._success(
            capability,
            data={
                "id": publishable.get("id", "") or "",
                "title": publishable.get("title", "") or "",
                "kind": (publishable.get("__typename", "") or "").lower(),
                "publication_count": len(publication_ids),
            },
        )
