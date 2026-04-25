"""ShopifyFilesAdapter — upload images / files into the store's CDN.

ShopAI's creative pipeline outputs image URLs (DALL-E / Imagen / Midjourney
proxy / scraped product photos). To attach them to products, blog posts,
or theme assets, those URLs have to be pulled into Shopify's CDN first
— Shopify rejects raw external URLs in product image fields and only
trusts assets it has fetched and re-hosted.

The Files API exposes that pull via two GraphQL primitives:

  * ``fileCreate`` with ``originalSource`` set to a public URL —
    Shopify fetches the asset asynchronously, then exposes a
    ``files/...`` CDN URL once ``fileStatus`` flips to ``READY``.
  * ``files`` query — paginated list of every file in the shop's
    library, useful for cleanup / dedup tooling.

Capabilities:

  * ``SHOPIFY_UPLOAD_FILE`` — mint 1..N file records from public URLs.
    Returns immediately with ``fileStatus`` (usually ``UPLOADED`` then
    asynchronously ``READY``); the adapter does NOT poll for ``READY``,
    that's the caller's job if it needs the final CDN URL.
  * ``SHOPIFY_LIST_FILES`` — page through ``files`` with cursor.

Local file uploads (multipart staged) are intentionally out of scope for
this pass — every ShopAI consumer has a URL handy because the upstream
generators are HTTP services. We can add a staged-upload path later
if/when an offline pipeline needs it.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FILE_CREATE_MUTATION = """
mutation fileCreate($files: [FileCreateInput!]!) {
  fileCreate(files: $files) {
    files {
      id
      fileStatus
      alt
      createdAt
      ... on MediaImage {
        image {
          url
          width
          height
        }
        mimeType
      }
      ... on GenericFile {
        url
        originalFileSize
        mimeType
      }
      ... on Video {
        sources {
          url
          mimeType
          format
          height
          width
        }
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_FILES_LIST_QUERY = """
query files($first: Int!, $after: String, $query: String) {
  files(first: $first, after: $after, query: $query) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        fileStatus
        alt
        createdAt
        ... on MediaImage {
          image {
            url
            width
            height
          }
          mimeType
        }
        ... on GenericFile {
          url
          originalFileSize
          mimeType
        }
        ... on Video {
          sources {
            url
            mimeType
            format
          }
        }
      }
    }
  }
}
""".strip()


# Shopify caps ``fileCreate`` at 250 inputs per call. Most callers
# upload 1-10 at a time so we just enforce the API ceiling rather
# than chunking; bigger payloads should batch on their side.
_MAX_FILES_PER_CALL = 250

# ``files`` query default — keep small to stay under the GraphQL
# cost budget. Caller can ask for up to 250 per page (Shopify's hard
# cap), beyond that the adapter clamps.
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


# Map of friendly content types ShopAI callers use → Shopify enum
# values accepted by ``FileContentType``. Anything not in this map
# defaults to ``IMAGE`` because that's >95% of the creative pipeline
# output.
_CONTENT_TYPE_ALIASES = {
    "image": "IMAGE",
    "img": "IMAGE",
    "photo": "IMAGE",
    "picture": "IMAGE",
    "video": "VIDEO",
    "mp4": "VIDEO",
    "file": "FILE",
    "pdf": "FILE",
    "doc": "FILE",
}


class ShopifyFilesAdapter(ShopifyBaseAdapter):
    name = "shopify_files"
    capabilities = {
        Capability.SHOPIFY_UPLOAD_FILE,
        Capability.SHOPIFY_LIST_FILES,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPLOAD_FILE:
            return self._upload_files(params)
        if capability == Capability.SHOPIFY_LIST_FILES:
            return self._list_files(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Upload ─────────────────────────────────────────────────────

    def _upload_files(self, params: dict[str, Any]) -> Any:
        files_input = self._build_file_inputs(params)
        data = self._gql(
            _FILE_CREATE_MUTATION,
            {"files": files_input},
        )
        self._check_user_errors(data, "fileCreate")
        payload = data.get("fileCreate") or {}
        files = payload.get("files") or []
        return self._success(
            Capability.SHOPIFY_UPLOAD_FILE,
            data={
                "uploaded": len(files),
                "files": [self._normalise_file(f) for f in files],
            },
        )

    @staticmethod
    def _build_file_inputs(params: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert ShopAI's friendly call shape into a list of
        ``FileCreateInput`` dicts.

        Accepts either::

            # single
            {"url": "https://...", "alt": "Product hero", "type": "image"}

            # batch
            {"files": [
                {"url": "...", "alt": "..."},
                {"url": "...", "alt": "..."},
            ]}

        Raises ``AdapterValidationError`` on malformed input so the
        call fails fast instead of paying for a userErrors round-trip.
        """
        # Accept both single-file and batch shapes; normalise to a list.
        if "files" in params:
            raw_list = params["files"]
            if not isinstance(raw_list, list) or not raw_list:
                raise AdapterValidationError(
                    "shopify_files", "'files' must be a non-empty list",
                )
        elif "url" in params:
            raw_list = [{
                k: v for k, v in params.items()
                if k in ("url", "alt", "type", "filename")
            }]
        else:
            raise AdapterValidationError(
                "shopify_files",
                "either 'url' (single) or 'files' (list) is required",
            )

        if len(raw_list) > _MAX_FILES_PER_CALL:
            raise AdapterValidationError(
                "shopify_files",
                f"max {_MAX_FILES_PER_CALL} files per call, got {len(raw_list)}",
            )

        out: list[dict[str, Any]] = []
        for i, entry in enumerate(raw_list):
            if not isinstance(entry, dict):
                raise AdapterValidationError(
                    "shopify_files", f"files[{i}] is not a dict",
                )
            url = entry.get("url") or entry.get("originalSource")
            if not isinstance(url, str) or not url.strip():
                raise AdapterValidationError(
                    "shopify_files",
                    f"files[{i}] missing required 'url'",
                )
            url = url.strip()
            # Shopify only fetches public http(s) URLs. Reject obvious
            # local paths and data: URIs early — both fail at fetch
            # time anyway, but the userErrors message is opaque.
            if not (url.startswith("http://") or url.startswith("https://")):
                raise AdapterValidationError(
                    "shopify_files",
                    f"files[{i}] 'url' must be http(s); got {url[:30]!r}",
                )

            content_type_raw = entry.get("type") or entry.get("contentType") or "image"
            if not isinstance(content_type_raw, str):
                raise AdapterValidationError(
                    "shopify_files",
                    f"files[{i}] 'type' must be a string",
                )
            content_type = _CONTENT_TYPE_ALIASES.get(
                content_type_raw.lower(),
                content_type_raw.upper(),
            )
            if content_type not in ("IMAGE", "VIDEO", "FILE"):
                raise AdapterValidationError(
                    "shopify_files",
                    f"files[{i}] 'type' must be one of IMAGE/VIDEO/FILE, "
                    f"got {content_type_raw!r}",
                )

            file_input: dict[str, Any] = {
                "originalSource": url,
                "contentType": content_type,
            }
            alt = entry.get("alt")
            if alt is not None:
                if not isinstance(alt, str):
                    raise AdapterValidationError(
                        "shopify_files",
                        f"files[{i}] 'alt' must be a string",
                    )
                # Shopify caps alt at 512 chars; truncate gracefully
                # rather than failing the whole batch on one long
                # caption.
                file_input["alt"] = alt[:512]
            filename = entry.get("filename")
            if filename is not None:
                if not isinstance(filename, str):
                    raise AdapterValidationError(
                        "shopify_files",
                        f"files[{i}] 'filename' must be a string",
                    )
                file_input["filename"] = filename
            out.append(file_input)
        return out

    @staticmethod
    def _normalise_file(node: dict[str, Any]) -> dict[str, Any]:
        """Flatten a Shopify file node into the same shape regardless
        of whether it's a MediaImage / GenericFile / Video.

        Callers typically just want ``url`` and ``status``; the union
        types from the GraphQL schema force the field to live in
        different sub-objects depending on the kind, so we lift them
        to the top level here.
        """
        if not isinstance(node, dict):
            return {}
        kind = "image"
        url = ""
        width = 0
        height = 0
        mime = node.get("mimeType", "")
        size = node.get("originalFileSize")

        # MediaImage path
        image = node.get("image")
        if isinstance(image, dict):
            url = image.get("url", "") or ""
            width = int(image.get("width", 0) or 0)
            height = int(image.get("height", 0) or 0)
            kind = "image"
        # GenericFile path
        elif node.get("url"):
            url = node.get("url", "") or ""
            kind = "file"
        # Video path
        elif isinstance(node.get("sources"), list) and node["sources"]:
            src = node["sources"][0]
            if isinstance(src, dict):
                url = src.get("url", "") or ""
                width = int(src.get("width", 0) or 0)
                height = int(src.get("height", 0) or 0)
                mime = src.get("mimeType", "") or mime
            kind = "video"

        return {
            "id": node.get("id", ""),
            "kind": kind,
            "status": node.get("fileStatus", ""),
            "url": url,
            "alt": node.get("alt", "") or "",
            "width": width,
            "height": height,
            "mime_type": mime,
            "size_bytes": int(size) if isinstance(size, (int, str)) and str(size).isdigit() else 0,
            "created_at": node.get("createdAt", ""),
        }

    # ── List ───────────────────────────────────────────────────────

    def _list_files(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_files", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_files", "'query' must be a string or None",
            )

        data = self._gql(
            _FILES_LIST_QUERY,
            {"first": limit, "after": cursor, "query": query},
        )
        envelope = data.get("files") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        files = [
            self._normalise_file(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_FILES,
            data={
                "files": files,
                "count": len(files),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )
