"""ShopifyScriptTagsAdapter — storefront JS injection.

A script tag is a remote JavaScript URL Shopify injects into every
storefront page (and optionally the order-status page). The script
runs in the customer's browser. Common engine uses:

  * **Pixel layer beyond Shopify Web Pixels.** When the analytics
    engine needs first-party event tracking that goes BEYOND what
    Web Pixels API permits (raw DOM access, A/B test assignment,
    fingerprinting, ...).
  * **Storefront UI overlays.** Cart-saver popup, exit-intent
    discount banners, AI-generated trust badges — anything the
    creative engine generates and the merchant doesn't want to
    edit theme code for.
  * **Legacy app shims.** Some third-party apps still register
    via ScriptTag rather than the newer App Embed surface.

Capabilities:

  * ``SHOPIFY_LIST_SCRIPT_TAGS``    — list registered scripts.
  * ``SHOPIFY_CREATE_SCRIPT_TAG``   — register a new script URL.
  * ``SHOPIFY_UPDATE_SCRIPT_TAG``   — update src / display_scope.
  * ``SHOPIFY_DELETE_SCRIPT_TAG``   — unregister.

Friendly create call shape::

    {"src":            "https://cdn.shopai.dev/exit-intent.js",
     "display_scope":  "ONLINE_STORE",   # or ORDER_STATUS or ALL
     "cache":          False}

Pattern E note: gated by ``write_script_tags`` scope. Note that
Shopify is steering apps away from ScriptTag toward App Embed
blocks (managed via theme.app extensions); this adapter still
exists for engines integrating with stores that haven't migrated
or have specific needs ScriptTag uniquely covers.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SCRIPT_TAG_FIELDS = """
id
src
displayScope
cache
createdAt
updatedAt
""".strip()


_LIST_SCRIPT_TAGS_QUERY = f"""
query scriptTags(
  $first: Int!,
  $after: String,
  $src: URL
) {{
  scriptTags(first: $first, after: $after, src: $src) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_SCRIPT_TAG_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_SCRIPT_TAG_MUTATION = f"""
mutation scriptTagCreate($input: ScriptTagInput!) {{
  scriptTagCreate(input: $input) {{
    scriptTag {{
      {_SCRIPT_TAG_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_SCRIPT_TAG_MUTATION = f"""
mutation scriptTagUpdate($id: ID!, $input: ScriptTagInput!) {{
  scriptTagUpdate(id: $id, input: $input) {{
    scriptTag {{
      {_SCRIPT_TAG_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_SCRIPT_TAG_MUTATION = """
mutation scriptTagDelete($id: ID!) {
  scriptTagDelete(id: $id) {
    deletedScriptTagId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_DISPLAY_SCOPES = {"ONLINE_STORE", "ORDER_STATUS", "ALL"}


class ShopifyScriptTagsAdapter(ShopifyBaseAdapter):
    name = "shopify_script_tags"
    capabilities = {
        Capability.SHOPIFY_LIST_SCRIPT_TAGS,
        Capability.SHOPIFY_CREATE_SCRIPT_TAG,
        Capability.SHOPIFY_UPDATE_SCRIPT_TAG,
        Capability.SHOPIFY_DELETE_SCRIPT_TAG,
    }
    required_scopes = frozenset({"read_script_tags", "write_script_tags"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_SCRIPT_TAGS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_SCRIPT_TAG:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_SCRIPT_TAG:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_SCRIPT_TAG:
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

        # Optional src URL filter — surfaces "is this URL already
        # registered?" without paginating the entire list.
        src_filter = params.get("src")
        if src_filter is not None:
            if not isinstance(src_filter, str) or not src_filter.strip():
                raise AdapterValidationError(
                    self.name, "'src' must be a non-empty string",
                )
            variables["src"] = src_filter.strip()

        data = self._gql(_LIST_SCRIPT_TAGS_QUERY, variables)
        envelope = data.get("scriptTags") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        tags = [
            self._normalise_tag(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_SCRIPT_TAGS,
            data={
                "script_tags": tags,
                "count": len(tags),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        tag_input = self._build_input(params, for_update=False)
        data = self._gql(_CREATE_SCRIPT_TAG_MUTATION, {"input": tag_input})
        self._check_user_errors(data, "scriptTagCreate")
        payload = data.get("scriptTagCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_SCRIPT_TAG,
            data={
                "script_tag": self._normalise_tag(
                    payload.get("scriptTag") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        tag_id = params.get("id") or params.get("script_tag_id")
        if not isinstance(tag_id, str) or not tag_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the script tag) is required",
            )
        tag_input = self._build_input(params, for_update=True)
        if not tag_input:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (src, display_scope, cache)",
            )
        data = self._gql(_UPDATE_SCRIPT_TAG_MUTATION, {
            "id": tag_id.strip(),
            "input": tag_input,
        })
        self._check_user_errors(data, "scriptTagUpdate")
        payload = data.get("scriptTagUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SCRIPT_TAG,
            data={
                "script_tag": self._normalise_tag(
                    payload.get("scriptTag") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        tag_id = params.get("id") or params.get("script_tag_id")
        if not isinstance(tag_id, str) or not tag_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the script tag) is required",
            )
        data = self._gql(_DELETE_SCRIPT_TAG_MUTATION, {"id": tag_id.strip()})
        self._check_user_errors(data, "scriptTagDelete")
        payload = data.get("scriptTagDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_SCRIPT_TAG,
            data={
                "deleted_id": (
                    payload.get("deletedScriptTagId", "") or ""
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        src = params.get("src")
        if src is not None:
            if not isinstance(src, str) or not src.strip():
                raise AdapterValidationError(
                    self.name, "'src' must be a non-empty string",
                )
            if not src.startswith("https://"):
                # Shopify rejects http:// for security; fail-fast at
                # the validator beats burning a GraphQL hop.
                raise AdapterValidationError(
                    self.name,
                    "'src' must start with https:// (Shopify rejects "
                    "non-TLS script tag URLs)",
                )
            out["src"] = src.strip()

        if not for_update and "src" not in out:
            raise AdapterValidationError(
                self.name, "'src' is required to create a script tag",
            )

        display_scope = params.get("display_scope") or params.get(
            "displayScope"
        )
        if display_scope is not None:
            if (
                not isinstance(display_scope, str)
                or display_scope.upper() not in _VALID_DISPLAY_SCOPES
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'display_scope' must be one of: "
                    f"{sorted(_VALID_DISPLAY_SCOPES)}",
                )
            out["displayScope"] = display_scope.upper()

        cache = params.get("cache")
        if cache is not None:
            out["cache"] = bool(cache)

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_tag(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "src": node.get("src", "") or "",
            "display_scope": node.get("displayScope", "") or "",
            "cache": bool(node.get("cache", False)),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
