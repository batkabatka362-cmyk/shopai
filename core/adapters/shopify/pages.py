"""ShopifyPagesAdapter — CMS static pages CRUD.

Online-store pages are the static-content surface ("About Us",
"Shipping & Returns", "FAQ", landing pages for ad campaigns).
ShopAI's content + SEO engines write these. The legacy REST
``/admin/api/.../pages.json`` is what most engines reach for; this
adapter is the GraphQL counterpart so the rest of the codebase
keeps a single style.

Capabilities:

  * ``SHOPIFY_LIST_PAGES``    — paginated list with filter/sort.
  * ``SHOPIFY_GET_PAGE``      — single page (id or handle).
  * ``SHOPIFY_CREATE_PAGE``   — create with title + body HTML.
  * ``SHOPIFY_UPDATE_PAGE``   — update title / body / handle / SEO.
  * ``SHOPIFY_DELETE_PAGE``   — delete.

Friendly call shape::

    create::
      {"title":      "Holiday Returns",
       "body_html":  "<p>Extended through Jan 31.</p>",
       "handle":     "holiday-returns",
       "is_published": True}

The ``page`` GraphQL surface returns ``Page`` nodes with the same
fields the REST API does — title, body (HTML stored in body),
handle, templateSuffix, publishedAt.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PAGE_FIELDS = """
id
title
handle
body
bodySummary
templateSuffix
isPublished
publishedAt
createdAt
updatedAt
""".strip()


_LIST_PAGES_QUERY = f"""
query pages(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: PageSortKeys,
  $reverse: Boolean
) {{
  pages(
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
        {_PAGE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_PAGE_QUERY = f"""
query page($id: ID!) {{
  page(id: $id) {{
    {_PAGE_FIELDS}
  }}
}}
""".strip()


_CREATE_PAGE_MUTATION = f"""
mutation pageCreate($page: PageCreateInput!) {{
  pageCreate(page: $page) {{
    page {{
      {_PAGE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_PAGE_MUTATION = f"""
mutation pageUpdate($id: ID!, $page: PageUpdateInput!) {{
  pageUpdate(id: $id, page: $page) {{
    page {{
      {_PAGE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_PAGE_MUTATION = """
mutation pageDelete($id: ID!) {
  pageDelete(id: $id) {
    deletedPageId
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

_VALID_SORT_KEYS = {
    "TITLE", "UPDATED_AT", "CREATED_AT", "PUBLISHED_AT",
    "ID", "RELEVANCE",
}


class ShopifyPagesAdapter(ShopifyBaseAdapter):
    name = "shopify_pages"
    capabilities = {
        Capability.SHOPIFY_LIST_PAGES,
        Capability.SHOPIFY_GET_PAGE,
        Capability.SHOPIFY_CREATE_PAGE,
        Capability.SHOPIFY_UPDATE_PAGE,
        Capability.SHOPIFY_DELETE_PAGE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PAGES:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_PAGE:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_PAGE:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_PAGE:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_PAGE:
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

        data = self._gql(_LIST_PAGES_QUERY, variables)
        envelope = data.get("pages") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        pages = [
            self._normalise_page(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PAGES,
            data={
                "pages": pages,
                "count": len(pages),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        page_id = params.get("id") or params.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the page) is required",
            )
        data = self._gql(_GET_PAGE_QUERY, {"id": page_id.strip()})
        node = data.get("page") or {}
        return self._success(
            Capability.SHOPIFY_GET_PAGE,
            data={
                "page": self._normalise_page(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        page_input = self._build_page_input(params, for_update=False)
        data = self._gql(_CREATE_PAGE_MUTATION, {"page": page_input})
        self._check_user_errors(data, "pageCreate")
        payload = data.get("pageCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PAGE,
            data={
                "page": self._normalise_page(payload.get("page") or {}),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        page_id = params.get("id") or params.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the page) is required",
            )
        page_input = self._build_page_input(params, for_update=True)
        if not page_input:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (title, body_html, handle, "
                "is_published, template_suffix)",
            )
        data = self._gql(_UPDATE_PAGE_MUTATION, {
            "id": page_id.strip(),
            "page": page_input,
        })
        self._check_user_errors(data, "pageUpdate")
        payload = data.get("pageUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_PAGE,
            data={
                "page": self._normalise_page(payload.get("page") or {}),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        page_id = params.get("id") or params.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the page) is required",
            )
        data = self._gql(_DELETE_PAGE_MUTATION, {"id": page_id.strip()})
        self._check_user_errors(data, "pageDelete")
        payload = data.get("pageDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PAGE,
            data={
                "deleted_id": payload.get("deletedPageId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_page_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        title = params.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    self.name, "'title' must be a string",
                )
            if title.strip():
                out["title"] = title.strip()

        if not for_update and "title" not in out:
            raise AdapterValidationError(
                self.name, "'title' is required to create a page",
            )

        body = params.get("body_html") or params.get("body")
        if body is not None:
            if not isinstance(body, str):
                raise AdapterValidationError(
                    self.name, "'body_html' must be a string",
                )
            out["body"] = body

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str):
                raise AdapterValidationError(
                    self.name, "'handle' must be a string",
                )
            out["handle"] = handle.strip()

        template_suffix = params.get("template_suffix") or params.get(
            "templateSuffix"
        )
        if template_suffix is not None:
            if not isinstance(template_suffix, str):
                raise AdapterValidationError(
                    self.name, "'template_suffix' must be a string",
                )
            out["templateSuffix"] = template_suffix

        is_published = params.get("is_published")
        if is_published is None:
            is_published = params.get("isPublished")
        if is_published is not None:
            out["isPublished"] = bool(is_published)

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_page(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "body_html": node.get("body", "") or "",
            "body_summary": node.get("bodySummary", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "is_published": bool(node.get("isPublished", False)),
            "published_at": node.get("publishedAt", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
