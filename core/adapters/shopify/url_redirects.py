"""ShopifyUrlRedirectsAdapter — storefront URL redirects.

Storefront URL redirects map a SOURCE path on the merchant's domain
to a TARGET path or absolute URL — Shopify's online store rewrites
the request before the renderer sees it. Critical for SEO during
content reorganisations:

  * The merchant retires an old "/products/old-sku" page and points
    it at "/products/new-sku" so search engines preserve link juice.
  * The migration engine rewires every "/blogs/old-blog/*" path to
    the corresponding "/blogs/new-blog/*" after Phase 24.1 renamed
    the blog.
  * Bulk-clean stale redirects accumulated during a chaotic launch.

Capabilities:

  * ``SHOPIFY_LIST_URL_REDIRECTS``        — paginated list with
    optional sort_key (Pattern D — narrow enum: ID / PATH /
    RELEVANCE), savedSearchId, query.
  * ``SHOPIFY_GET_URL_REDIRECT``          — single redirect by GID.
  * ``SHOPIFY_CREATE_URL_REDIRECT``       — urlRedirectCreate.
    Pattern A: body wrapped in ``urlRedirect`` arg of type
    ``UrlRedirectInput`` (path + target).
  * ``SHOPIFY_UPDATE_URL_REDIRECT``       — urlRedirectUpdate.
    Pattern A: id at field level + ``urlRedirect`` body.
  * ``SHOPIFY_DELETE_URL_REDIRECT``       — urlRedirectDelete.
  * ``SHOPIFY_BULK_DELETE_URL_REDIRECTS`` — wraps ALL FOUR bulk-
    delete variants (ids / search / saved_search_id / all) under
    one capability with a selector. Returns the async Job id —
    callers poll via the bulk-operation adapter.

Friendly call shape (create / update)::

    {"path":   "/products/old-sku",
     "target": "/products/new-sku"}

Friendly call shape (bulk delete)::

    {"ids":               ["gid://...","..."]}   # one of these
    {"search":            "path:/old-*"}         # ←
    {"saved_search_id":   "gid://shopify/SavedSearch/123"}
    {"all":               True}                  # nuke them all

Pattern A — id at field level on the single-resource mutations.
Pattern D — UrlRedirectSortKeys is narrow (ID / PATH / RELEVANCE).
Pattern F — UrlRedirectUserError HAS code (introspection
confirmed: fields ['code', 'field', 'message']). Selection keeps it.

Pattern E note: gated by ``read_online_store_navigation`` /
``write_online_store_navigation`` scopes.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_REDIRECT_FIELDS = """
id
path
target
""".strip()


_LIST_QUERY = f"""
query urlRedirects(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: UrlRedirectSortKeys,
  $reverse: Boolean,
  $savedSearchId: ID
) {{
  urlRedirects(
    first: $first, after: $after,
    query: $query, sortKey: $sortKey,
    reverse: $reverse, savedSearchId: $savedSearchId
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_REDIRECT_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_QUERY = f"""
query urlRedirect($id: ID!) {{
  urlRedirect(id: $id) {{
    {_REDIRECT_FIELDS}
  }}
}}
""".strip()


_CREATE_MUTATION = f"""
mutation urlRedirectCreate(
  $urlRedirect: UrlRedirectInput!
) {{
  urlRedirectCreate(urlRedirect: $urlRedirect) {{
    urlRedirect {{
      {_REDIRECT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_MUTATION = f"""
mutation urlRedirectUpdate(
  $id: ID!,
  $urlRedirect: UrlRedirectInput!
) {{
  urlRedirectUpdate(id: $id, urlRedirect: $urlRedirect) {{
    urlRedirect {{
      {_REDIRECT_FIELDS}
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
mutation urlRedirectDelete($id: ID!) {
  urlRedirectDelete(id: $id) {
    deletedUrlRedirectId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_BULK_DELETE_BY_IDS = """
mutation urlRedirectBulkDeleteByIds($ids: [ID!]!) {
  urlRedirectBulkDeleteByIds(ids: $ids) {
    job { id done }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_BULK_DELETE_BY_SEARCH = """
mutation urlRedirectBulkDeleteBySearch($search: String!) {
  urlRedirectBulkDeleteBySearch(search: $search) {
    job { id done }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_BULK_DELETE_BY_SAVED_SEARCH = """
mutation urlRedirectBulkDeleteBySavedSearch($savedSearchId: ID!) {
  urlRedirectBulkDeleteBySavedSearch(savedSearchId: $savedSearchId) {
    job { id done }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_BULK_DELETE_ALL = """
mutation urlRedirectBulkDeleteAll {
  urlRedirectBulkDeleteAll {
    job { id done }
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
_VALID_SORT_KEYS = {"ID", "PATH", "RELEVANCE"}


class ShopifyUrlRedirectsAdapter(ShopifyBaseAdapter):
    name = "shopify_url_redirects"
    capabilities = {
        Capability.SHOPIFY_LIST_URL_REDIRECTS,
        Capability.SHOPIFY_GET_URL_REDIRECT,
        Capability.SHOPIFY_CREATE_URL_REDIRECT,
        Capability.SHOPIFY_UPDATE_URL_REDIRECT,
        Capability.SHOPIFY_DELETE_URL_REDIRECT,
        Capability.SHOPIFY_BULK_DELETE_URL_REDIRECTS,
    }
    required_scopes = frozenset({"read_content", "write_content"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_URL_REDIRECTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_URL_REDIRECT:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_URL_REDIRECT:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_URL_REDIRECT:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_URL_REDIRECT:
            return self._delete(params)
        if capability == Capability.SHOPIFY_BULK_DELETE_URL_REDIRECTS:
            return self._bulk_delete(params)
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

        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    self.name, "'sort_key' must be a string",
                )
            sort_key = sort_key.strip().upper()
            if sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of "
                    f"{sorted(_VALID_SORT_KEYS)}",
                )

        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                self.name, "'query' must be a string or None",
            )

        saved_search_id = (
            params.get("saved_search_id")
            or params.get("savedSearchId")
        )
        if saved_search_id is not None and not isinstance(
            saved_search_id, str,
        ):
            raise AdapterValidationError(
                self.name,
                "'saved_search_id' must be a string or None",
            )

        reverse = params.get("reverse")
        data = self._gql(_LIST_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": bool(reverse) if reverse is not None else None,
            "savedSearchId": saved_search_id,
        })
        envelope = data.get("urlRedirects") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        redirects = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_URL_REDIRECTS,
            data={
                "redirects": redirects,
                "count": len(redirects),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        redirect_id = self._extract_id(params)
        data = self._gql(_GET_QUERY, {"id": redirect_id})
        node = data.get("urlRedirect") or {}
        return self._success(
            Capability.SHOPIFY_GET_URL_REDIRECT,
            data={
                "redirect": self._normalise(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        body = self._build_input(params, require_both=True)
        data = self._gql(_CREATE_MUTATION, {"urlRedirect": body})
        self._check_user_errors(data, "urlRedirectCreate")
        payload = data.get("urlRedirectCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_URL_REDIRECT,
            data={
                "redirect": self._normalise(
                    payload.get("urlRedirect") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        redirect_id = self._extract_id(params)
        body = self._build_input(params, require_both=False)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'path' / 'target'",
            )
        data = self._gql(_UPDATE_MUTATION, {
            "id": redirect_id, "urlRedirect": body,
        })
        self._check_user_errors(data, "urlRedirectUpdate")
        payload = data.get("urlRedirectUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_URL_REDIRECT,
            data={
                "redirect": self._normalise(
                    payload.get("urlRedirect") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        redirect_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {"id": redirect_id})
        self._check_user_errors(data, "urlRedirectDelete")
        payload = data.get("urlRedirectDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_URL_REDIRECT,
            data={
                "deleted_id": payload.get("deletedUrlRedirectId", "")
                or "",
            },
        )

    # ── Bulk delete ────────────────────────────────────────────────

    def _bulk_delete(self, params: dict[str, Any]) -> Any:
        ids = params.get("ids")
        search = params.get("search")
        saved_search_id = (
            params.get("saved_search_id")
            or params.get("savedSearchId")
        )
        delete_all = params.get("all")

        present = [
            (k, v) for k, v in (
                ("ids", ids),
                ("search", search),
                ("saved_search_id", saved_search_id),
                ("all", delete_all),
            ) if v not in (None, "", [], False)
        ]
        if not present:
            raise AdapterValidationError(
                self.name,
                "supply exactly one of 'ids' / 'search' / "
                "'saved_search_id' / 'all'",
            )
        if len(present) > 1:
            raise AdapterValidationError(
                self.name,
                f"only one of 'ids' / 'search' / 'saved_search_id' "
                f"/ 'all' may be set; got "
                f"{[n for n, _ in present]}",
            )
        kind, value = present[0]

        if kind == "ids":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value
            ):
                raise AdapterValidationError(
                    self.name,
                    "'ids' must be a list of GID strings",
                )
            cleaned = [v.strip() for v in value if v.strip()]
            if not cleaned:
                raise AdapterValidationError(
                    self.name, "'ids' contained only blanks",
                )
            data = self._gql(_BULK_DELETE_BY_IDS, {"ids": cleaned})
            op_name = "urlRedirectBulkDeleteByIds"
            summary = {"kind": "ids", "count": len(cleaned)}
        elif kind == "search":
            if not isinstance(value, str) or not value.strip():
                raise AdapterValidationError(
                    self.name, "'search' must be a non-empty string",
                )
            data = self._gql(_BULK_DELETE_BY_SEARCH, {
                "search": value.strip(),
            })
            op_name = "urlRedirectBulkDeleteBySearch"
            summary = {"kind": "search", "query": value.strip()}
        elif kind == "saved_search_id":
            if not isinstance(value, str) or not value.strip():
                raise AdapterValidationError(
                    self.name,
                    "'saved_search_id' must be a Shopify GID string",
                )
            data = self._gql(_BULK_DELETE_BY_SAVED_SEARCH, {
                "savedSearchId": value.strip(),
            })
            op_name = "urlRedirectBulkDeleteBySavedSearch"
            summary = {
                "kind": "saved_search",
                "saved_search_id": value.strip(),
            }
        else:  # all
            data = self._gql(_BULK_DELETE_ALL, {})
            op_name = "urlRedirectBulkDeleteAll"
            summary = {"kind": "all"}

        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_BULK_DELETE_URL_REDIRECTS,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False)
                    if isinstance(job, dict) else False
                ),
                "selector": summary,
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        redirect_id = (
            params.get("id")
            or params.get("redirect_id")
            or params.get("urlRedirectId")
        )
        if not isinstance(redirect_id, str) or \
                not redirect_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the URL redirect) is required",
            )
        return redirect_id.strip()

    def _build_input(
        self, params: dict[str, Any], *, require_both: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        path = params.get("path")
        if path is not None:
            if not isinstance(path, str) or not path.strip():
                raise AdapterValidationError(
                    self.name, "'path' must be a non-empty string",
                )
            out["path"] = path.strip()
        target = params.get("target")
        if target is not None:
            if not isinstance(target, str) or not target.strip():
                raise AdapterValidationError(
                    self.name, "'target' must be a non-empty string",
                )
            out["target"] = target.strip()
        if require_both:
            if "path" not in out:
                raise AdapterValidationError(
                    self.name,
                    "'path' is required (the from-path on the "
                    "merchant's domain)",
                )
            if "target" not in out:
                raise AdapterValidationError(
                    self.name,
                    "'target' is required (where to redirect to)",
                )
        return out

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "path": node.get("path", "") or "",
            "target": node.get("target", "") or "",
        }
