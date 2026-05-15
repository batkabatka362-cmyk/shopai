"""ShopifyThemesAdapter — read storefront theme state, inject content.

Theme files (Liquid templates / sections / snippets / assets) are how
the storefront actually renders product pages, the cart drawer, the
checkout banner — all the places where ShopAI's engines have a stake.
Without an adapter the engines can plan content but not put it on
the storefront; merchants have to install snippets manually.

Two flows ShopAI engines need:

  * **Inject content snippets.** "Add the FAQ accordion section",
    "Install the sticky-cart snippet", "Update the trust-badge
    section with new copy" — all of these are
    ``themeFilesUpsert`` calls writing Liquid files into the live
    theme. The metaobjects adapter pairs with this: metaobjects hold
    the data, theme files reference them.

  * **Read theme state for opportunities.** The store-optimizer
    audits the theme to spot missing best practices (no
    Schema.org markup, no related-products section, no upsell on
    cart). That needs ``themes`` + ``themeFiles``.

Capabilities:

  * ``SHOPIFY_LIST_THEMES``         — page through themes on the shop.
  * ``SHOPIFY_LIST_THEME_FILES``    — list files (paths only, no body)
    in a specific theme; supports a ``filenames`` filter to fetch
    just the files we care about.
  * ``SHOPIFY_UPSERT_THEME_FILES``  — write/update Liquid / JSON /
    Asset files via ``themeFilesUpsert``. Caps at 50 files per call
    (Shopify's documented ceiling); larger payloads should chunk on
    the caller side.

Theme PUBLISH / theme switch is intentionally NOT in this pass —
swapping the live theme is a high-blast-radius action that wants
explicit operator approval rather than autonomous engine triggering.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_LIST_THEMES_QUERY = """
query themes($first: Int!, $after: String, $roles: [ThemeRole!]) {
  themes(first: $first, after: $after, roles: $roles) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        role
        processing
        createdAt
        updatedAt
      }
    }
  }
}
""".strip()


_LIST_THEME_FILES_QUERY = """
query themeFiles(
  $themeId: ID!, $first: Int!, $after: String, $filenames: [String!]
) {
  theme(id: $themeId) {
    id
    name
    files(first: $first, after: $after, filenames: $filenames) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        node {
          filename
          size
          contentType
          checksumMd5
          createdAt
          updatedAt
        }
      }
    }
  }
}
""".strip()


_UPSERT_THEME_FILES_MUTATION = """
mutation themeFilesUpsert($themeId: ID!, $files: [OnlineStoreThemeFilesUpsertFileInput!]!) {
  themeFilesUpsert(themeId: $themeId, files: $files) {
    upsertedThemeFiles {
      filename
    }
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
# Shopify caps themeFilesUpsert at 50 files per call. Caller chunks
# larger payloads — same convention as metafield's 25-per-call cap.
_MAX_UPSERT_FILES = 50

# ThemeRole enum aliases. Engines may pass natural words; map to
# canonical UPPER_SNAKE values Shopify expects.
_THEME_ROLES = {
    "main": "MAIN",            # the published theme
    "live": "MAIN",
    "published": "MAIN",
    "unpublished": "UNPUBLISHED",
    "demo": "DEMO",
    "development": "DEVELOPMENT",
    "dev": "DEVELOPMENT",
    "archived": "ARCHIVED",
    "locked": "LOCKED",
    "mobile": "MOBILE",
}


class ShopifyThemesAdapter(ShopifyBaseAdapter):
    name = "shopify_themes"
    capabilities = {
        Capability.SHOPIFY_LIST_THEMES,
        Capability.SHOPIFY_LIST_THEME_FILES,
        Capability.SHOPIFY_UPSERT_THEME_FILES,
    }
    required_scopes = frozenset({"read_themes", "write_themes"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_THEMES:
            return self._list_themes(params)
        if capability == Capability.SHOPIFY_LIST_THEME_FILES:
            return self._list_theme_files(params)
        if capability == Capability.SHOPIFY_UPSERT_THEME_FILES:
            return self._upsert_theme_files(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List themes ────────────────────────────────────────────────

    def _list_themes(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_themes", "'cursor' must be a string or None",
            )

        # Optional roles filter — engines often want only the live
        # ("main") theme, not every dev branch.
        raw_roles = params.get("roles") or params.get("role")
        roles_resolved: list[str] | None = None
        if raw_roles is not None:
            if isinstance(raw_roles, str):
                raw_roles = [raw_roles]
            if not isinstance(raw_roles, list):
                raise AdapterValidationError(
                    "shopify_themes",
                    "'roles' must be a string or list of strings",
                )
            roles_resolved = []
            for r in raw_roles:
                if not isinstance(r, str):
                    raise AdapterValidationError(
                        "shopify_themes",
                        "every entry in 'roles' must be a string",
                    )
                resolved = _THEME_ROLES.get(r.lower(), r.upper())
                roles_resolved.append(resolved)

        data = self._gql(_LIST_THEMES_QUERY, {
            "first": limit,
            "after": cursor,
            "roles": roles_resolved,
        })
        envelope = data.get("themes") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        themes: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            themes.append({
                "id": node.get("id", "") or "",
                "name": node.get("name", "") or "",
                "role": node.get("role", "") or "",
                "processing": bool(node.get("processing", False)),
                "created_at": node.get("createdAt", "") or "",
                "updated_at": node.get("updatedAt", "") or "",
            })
        return self._success(
            Capability.SHOPIFY_LIST_THEMES,
            data={
                "themes": themes,
                "count": len(themes),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── List theme files (metadata only) ───────────────────────────

    def _list_theme_files(self, params: dict[str, Any]) -> Any:
        theme_id = params.get("theme_id") or params.get("themeId")
        if not isinstance(theme_id, str) or not theme_id.strip():
            raise AdapterValidationError(
                "shopify_themes",
                "'theme_id' (Shopify GID for the theme) is required",
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
                "shopify_themes", "'cursor' must be a string or None",
            )

        filenames = params.get("filenames")
        if filenames is not None:
            if isinstance(filenames, str):
                filenames = [filenames]
            if not isinstance(filenames, list):
                raise AdapterValidationError(
                    "shopify_themes",
                    "'filenames' must be a string or list of strings",
                )
            for i, f in enumerate(filenames):
                if not isinstance(f, str):
                    raise AdapterValidationError(
                        "shopify_themes",
                        f"filenames[{i}] must be a string",
                    )

        data = self._gql(_LIST_THEME_FILES_QUERY, {
            "themeId": theme_id.strip(),
            "first": limit,
            "after": cursor,
            "filenames": filenames,
        })
        theme = data.get("theme")
        if not isinstance(theme, dict):
            return self._success(
                Capability.SHOPIFY_LIST_THEME_FILES,
                data={
                    "theme_id": theme_id.strip(),
                    "found": False,
                    "files": [],
                    "count": 0,
                    "has_next_page": False,
                    "end_cursor": "",
                },
            )
        files_envelope = theme.get("files") or {}
        page_info = files_envelope.get("pageInfo") or {}
        edges = files_envelope.get("edges") or []
        files: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            try:
                size = int(node.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            files.append({
                "filename": node.get("filename", "") or "",
                "size": size,
                "content_type": node.get("contentType", "") or "",
                "checksum_md5": node.get("checksumMd5", "") or "",
                "created_at": node.get("createdAt", "") or "",
                "updated_at": node.get("updatedAt", "") or "",
            })
        return self._success(
            Capability.SHOPIFY_LIST_THEME_FILES,
            data={
                "theme_id": theme.get("id", "") or theme_id.strip(),
                "theme_name": theme.get("name", "") or "",
                "found": True,
                "files": files,
                "count": len(files),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Upsert theme files ─────────────────────────────────────────

    def _upsert_theme_files(self, params: dict[str, Any]) -> Any:
        theme_id = params.get("theme_id") or params.get("themeId")
        if not isinstance(theme_id, str) or not theme_id.strip():
            raise AdapterValidationError(
                "shopify_themes",
                "'theme_id' (Shopify GID for the theme) is required",
            )

        files_input = self._build_files_input(params)
        data = self._gql(_UPSERT_THEME_FILES_MUTATION, {
            "themeId": theme_id.strip(),
            "files": files_input,
        })
        self._check_user_errors(data, "themeFilesUpsert")
        payload = data.get("themeFilesUpsert") or {}
        upserted = payload.get("upsertedThemeFiles") or []
        return self._success(
            Capability.SHOPIFY_UPSERT_THEME_FILES,
            data={
                "theme_id": theme_id.strip(),
                "upserted_count": len(upserted),
                "filenames": [
                    f.get("filename", "") for f in upserted
                    if isinstance(f, dict)
                ],
            },
        )

    @staticmethod
    def _build_files_input(params: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert ShopAI's friendly call shape into the
        ``OnlineStoreThemeFilesUpsertFileInput`` array.

        Accepts both single-file and batch shapes so callers can
        write one snippet without ceremony::

            # single
            {"theme_id": "...", "filename": "snippets/foo.liquid",
             "body": "{% comment %}...{% endcomment %}"}

            # batch
            {"theme_id": "...", "files": [
                {"filename": "snippets/foo.liquid", "body": "..."},
                {"filename": "sections/bar.liquid", "body": "..."},
            ]}

        Validates filename + body up-front so a malformed batch fails
        before any GraphQL hop.
        """
        if "files" in params:
            raw = params["files"]
            if not isinstance(raw, list) or not raw:
                raise AdapterValidationError(
                    "shopify_themes",
                    "'files' must be a non-empty list",
                )
        else:
            filename = params.get("filename")
            if not filename:
                raise AdapterValidationError(
                    "shopify_themes",
                    "either 'filename'+'body' (single) or 'files' "
                    "(list) is required",
                )
            raw = [{
                "filename": filename,
                "body": params.get("body"),
            }]

        if len(raw) > _MAX_UPSERT_FILES:
            raise AdapterValidationError(
                "shopify_themes",
                f"max {_MAX_UPSERT_FILES} files per call, got {len(raw)}",
            )

        out: list[dict[str, Any]] = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise AdapterValidationError(
                    "shopify_themes", f"files[{i}] must be a dict",
                )
            filename = entry.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                raise AdapterValidationError(
                    "shopify_themes",
                    f"files[{i}] missing required 'filename'",
                )
            # Body can be either inline text (Liquid / JSON) OR a URL
            # the asset should be fetched from. The GraphQL union
            # accepts both via the ``OnlineStoreThemeFileBodyInput``
            # input; we expose two ergonomic keys.
            inline_body = entry.get("body")
            url_body = entry.get("url") or entry.get("from_url")
            if inline_body is None and url_body is None:
                raise AdapterValidationError(
                    "shopify_themes",
                    f"files[{i}] needs 'body' (inline text) "
                    f"or 'url' (fetch from)",
                )
            if inline_body is not None and url_body is not None:
                raise AdapterValidationError(
                    "shopify_themes",
                    f"files[{i}] 'body' and 'url' are mutually exclusive",
                )
            if inline_body is not None:
                if not isinstance(inline_body, str):
                    raise AdapterValidationError(
                        "shopify_themes",
                        f"files[{i}] 'body' must be a string",
                    )
                body_input = {"type": "TEXT", "value": inline_body}
            else:
                if not isinstance(url_body, str) or not url_body.strip():
                    raise AdapterValidationError(
                        "shopify_themes",
                        f"files[{i}] 'url' must be a non-empty string",
                    )
                if not (url_body.startswith("http://")
                        or url_body.startswith("https://")):
                    raise AdapterValidationError(
                        "shopify_themes",
                        f"files[{i}] 'url' must be http(s)",
                    )
                body_input = {"type": "URL", "value": url_body.strip()}
            out.append({
                "filename": filename.strip(),
                "body": body_input,
            })
        return out
