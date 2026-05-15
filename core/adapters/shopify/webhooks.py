"""ShopifyWebhooksAdapter — webhook subscription management.

Webhooks turn Shopify into an event source for ShopAI. Without
them, every engine has to poll (expensive, laggy, scope-bound).
With them, Shopify pushes ``order_paid``, ``customer_created``,
``inventory_levels_update`` events to a ShopAI HTTP endpoint within
seconds of the change, and the brain layer reacts in near-real time.

Capabilities:

  * ``SHOPIFY_LIST_WEBHOOKS``   — list registered subscriptions.
  * ``SHOPIFY_CREATE_WEBHOOK``  — register a new subscription.
  * ``SHOPIFY_UPDATE_WEBHOOK``  — update endpoint / format.
  * ``SHOPIFY_DELETE_WEBHOOK``  — unregister.

Friendly call shape::

    {
      "topic":           "ORDERS_PAID",       # WebhookSubscriptionTopic enum
      "callback_url":    "https://ingest.shopai.dev/orders",
      "format":          "JSON",              # or XML
      "include_fields":  ["id", "name", "tags"],
    }

Topic names follow the GraphQL enum form (``ORDERS_PAID`` not
``orders/paid``). The adapter uppercases and normalises punctuation
so callers can pass either form.

Pattern A note: the create mutation takes the topic as a top-level
field plus the WebhookSubscriptionInput, not nested inside the input.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_WEBHOOK_FIELDS = """
id
topic
format
includeFields
createdAt
updatedAt
endpoint {
  __typename
  ... on WebhookHttpEndpoint {
    callbackUrl
  }
  ... on WebhookEventBridgeEndpoint {
    arn
  }
  ... on WebhookPubSubEndpoint {
    pubSubProject
    pubSubTopic
  }
}
""".strip()


_LIST_WEBHOOKS_QUERY = f"""
query webhookSubscriptions($first: Int!, $after: String) {{
  webhookSubscriptions(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_WEBHOOK_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_WEBHOOK_MUTATION = f"""
mutation webhookSubscriptionCreate(
  $topic: WebhookSubscriptionTopic!,
  $webhookSubscription: WebhookSubscriptionInput!
) {{
  webhookSubscriptionCreate(
    topic: $topic,
    webhookSubscription: $webhookSubscription
  ) {{
    webhookSubscription {{
      {_WEBHOOK_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_WEBHOOK_MUTATION = f"""
mutation webhookSubscriptionUpdate(
  $id: ID!,
  $webhookSubscription: WebhookSubscriptionInput!
) {{
  webhookSubscriptionUpdate(
    id: $id,
    webhookSubscription: $webhookSubscription
  ) {{
    webhookSubscription {{
      {_WEBHOOK_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_WEBHOOK_MUTATION = """
mutation webhookSubscriptionDelete($id: ID!) {
  webhookSubscriptionDelete(id: $id) {
    deletedWebhookSubscriptionId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


def _normalise_topic(raw: Any) -> str:
    """Accept either ``ORDERS_PAID`` or ``orders/paid`` form, return
    the GraphQL enum form. Shopify's REST API uses slashes, GraphQL
    uses underscores; engines coming from either side get the same
    coercion.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise AdapterValidationError(
            "shopify_webhooks", "'topic' is required",
        )
    return raw.strip().upper().replace("/", "_").replace("-", "_")


class ShopifyWebhooksAdapter(ShopifyBaseAdapter):
    name = "shopify_webhooks"
    capabilities = {
        Capability.SHOPIFY_LIST_WEBHOOKS,
        Capability.SHOPIFY_CREATE_WEBHOOK,
        Capability.SHOPIFY_UPDATE_WEBHOOK,
        Capability.SHOPIFY_DELETE_WEBHOOK,
    }
    required_scopes = frozenset({"read_webhooks", "write_webhooks"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_WEBHOOKS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_WEBHOOK:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_WEBHOOK:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_WEBHOOK:
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

        data = self._gql(_LIST_WEBHOOKS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("webhookSubscriptions") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        webhooks = [
            self._normalise_webhook(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_WEBHOOKS,
            data={
                "webhooks": webhooks,
                "count": len(webhooks),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        topic = _normalise_topic(params.get("topic"))
        sub_input = self._build_subscription_input(params)
        data = self._gql(_CREATE_WEBHOOK_MUTATION, {
            "topic": topic,
            "webhookSubscription": sub_input,
        })
        self._check_user_errors(data, "webhookSubscriptionCreate")
        payload = data.get("webhookSubscriptionCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_WEBHOOK,
            data={
                "webhook": self._normalise_webhook(
                    payload.get("webhookSubscription") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        webhook_id = params.get("id") or params.get("webhook_id")
        if not isinstance(webhook_id, str) or not webhook_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the webhook) is required",
            )
        sub_input = self._build_subscription_input(
            params, callback_required=False,
        )
        if not sub_input:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (callback_url, format, "
                "include_fields)",
            )
        data = self._gql(_UPDATE_WEBHOOK_MUTATION, {
            "id": webhook_id.strip(),
            "webhookSubscription": sub_input,
        })
        self._check_user_errors(data, "webhookSubscriptionUpdate")
        payload = data.get("webhookSubscriptionUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_WEBHOOK,
            data={
                "webhook": self._normalise_webhook(
                    payload.get("webhookSubscription") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        webhook_id = params.get("id") or params.get("webhook_id")
        if not isinstance(webhook_id, str) or not webhook_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the webhook) is required",
            )
        data = self._gql(_DELETE_WEBHOOK_MUTATION, {
            "id": webhook_id.strip(),
        })
        self._check_user_errors(data, "webhookSubscriptionDelete")
        payload = data.get("webhookSubscriptionDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_WEBHOOK,
            data={
                "deleted_id": (
                    payload.get("deletedWebhookSubscriptionId", "") or ""
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_subscription_input(
        self,
        params: dict[str, Any],
        callback_required: bool = True,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        callback_url = params.get("callback_url") or params.get("callbackUrl")
        if callback_url is not None:
            if not isinstance(callback_url, str) or not callback_url.strip():
                raise AdapterValidationError(
                    self.name, "'callback_url' must be a non-empty string",
                )
            if not callback_url.startswith(("http://", "https://")):
                raise AdapterValidationError(
                    self.name,
                    "'callback_url' must start with http:// or https://",
                )
            out["callbackUrl"] = callback_url.strip()
        elif callback_required:
            raise AdapterValidationError(
                self.name, "'callback_url' is required",
            )

        fmt = params.get("format")
        if fmt is not None:
            if not isinstance(fmt, str):
                raise AdapterValidationError(
                    self.name, "'format' must be a string",
                )
            fmt_upper = fmt.strip().upper()
            if fmt_upper not in {"JSON", "XML"}:
                raise AdapterValidationError(
                    self.name, "'format' must be 'JSON' or 'XML'",
                )
            out["format"] = fmt_upper

        include_fields = params.get("include_fields") or params.get(
            "includeFields"
        )
        if include_fields is not None:
            if not isinstance(include_fields, list) or not all(
                isinstance(f, str) for f in include_fields
            ):
                raise AdapterValidationError(
                    self.name,
                    "'include_fields' must be a list of strings",
                )
            out["includeFields"] = include_fields

        metafield_namespaces = params.get("metafield_namespaces")
        if metafield_namespaces is not None:
            if not isinstance(metafield_namespaces, list) or not all(
                isinstance(n, str) for n in metafield_namespaces
            ):
                raise AdapterValidationError(
                    self.name,
                    "'metafield_namespaces' must be a list of strings",
                )
            out["metafieldNamespaces"] = metafield_namespaces

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_webhook(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        endpoint = node.get("endpoint") or {}
        callback_url = ""
        endpoint_kind = ""
        if isinstance(endpoint, dict):
            endpoint_kind = endpoint.get("__typename", "") or ""
            callback_url = endpoint.get("callbackUrl", "") or ""
        return {
            "id": node.get("id", "") or "",
            "topic": node.get("topic", "") or "",
            "format": node.get("format", "") or "",
            "callback_url": callback_url,
            "endpoint_kind": endpoint_kind,
            "include_fields": list(node.get("includeFields") or []),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
