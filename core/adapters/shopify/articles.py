"""ShopifyArticlesAdapter — blog posts + blogs.

Blog articles are the long-form content surface — SEO articles, brand
storytelling, product launch posts. ShopAI's content engine
generates these automatically (via the LLM adapter) and the SEO
engine measures their performance.

Articles live inside Blogs (the merchant has 1..N blogs, each
holds N articles). The adapter exposes both: list blogs to discover
which container to write to, then list/CRUD articles within a blog.

Capabilities:

  * ``SHOPIFY_LIST_BLOGS``     — list available blogs (pick a target).
  * ``SHOPIFY_LIST_ARTICLES``  — list articles, optionally per blog.
  * ``SHOPIFY_GET_ARTICLE``    — single article with body HTML.
  * ``SHOPIFY_CREATE_ARTICLE`` — create within a specified blog.
  * ``SHOPIFY_UPDATE_ARTICLE`` — update title / body / handle / tags.
  * ``SHOPIFY_DELETE_ARTICLE`` — delete.

Friendly call shape::

    create::
      {"blog_id":     "gid://shopify/Blog/123",
       "title":       "10 Ways to Use Magnetic Levitation",
       "body_html":   "<p>...</p>",
       "author_name": "ShopAI Editorial",
       "tags":        ["product-launch", "seo"],
       "is_published": True}

Pattern D note: ``Article.authorV2`` was renamed to a simpler
``author { name }`` shape in 2024-01 — the legacy ``authorV2``
selection no longer compiles. The adapter queries the current form
and normalises ``author.name`` into ``author_name``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BLOG_FIELDS = """
id
title
handle
templateSuffix
commentPolicy
createdAt
updatedAt
""".strip()


_ARTICLE_FIELDS = """
id
title
handle
body
summary
templateSuffix
isPublished
publishedAt
createdAt
updatedAt
tags
author {
  name
}
image {
  url
  altText
}
blog {
  id
  title
  handle
}
""".strip()


_LIST_BLOGS_QUERY = f"""
query blogs(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: BlogSortKeys,
  $reverse: Boolean
) {{
  blogs(
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
        {_BLOG_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_LIST_ARTICLES_QUERY = f"""
query articles(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: ArticleSortKeys,
  $reverse: Boolean
) {{
  articles(
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
        {_ARTICLE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_ARTICLE_QUERY = f"""
query article($id: ID!) {{
  article(id: $id) {{
    {_ARTICLE_FIELDS}
  }}
}}
""".strip()


_CREATE_ARTICLE_MUTATION = f"""
mutation articleCreate($article: ArticleCreateInput!) {{
  articleCreate(article: $article) {{
    article {{
      {_ARTICLE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_ARTICLE_MUTATION = f"""
mutation articleUpdate($id: ID!, $article: ArticleUpdateInput!) {{
  articleUpdate(id: $id, article: $article) {{
    article {{
      {_ARTICLE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_ARTICLE_MUTATION = """
mutation articleDelete($id: ID!) {
  articleDelete(id: $id) {
    deletedArticleId
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

_VALID_BLOG_SORT_KEYS = {
    "TITLE", "HANDLE", "ID", "RELEVANCE",
}

_VALID_ARTICLE_SORT_KEYS = {
    "TITLE", "AUTHOR", "BLOG_TITLE", "PUBLISHED_AT", "UPDATED_AT",
    "ID", "RELEVANCE",
}


class ShopifyArticlesAdapter(ShopifyBaseAdapter):
    name = "shopify_articles"
    capabilities = {
        Capability.SHOPIFY_LIST_BLOGS,
        Capability.SHOPIFY_LIST_ARTICLES,
        Capability.SHOPIFY_GET_ARTICLE,
        Capability.SHOPIFY_CREATE_ARTICLE,
        Capability.SHOPIFY_UPDATE_ARTICLE,
        Capability.SHOPIFY_DELETE_ARTICLE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_BLOGS:
            return self._list_blogs(params)
        if capability == Capability.SHOPIFY_LIST_ARTICLES:
            return self._list_articles(params)
        if capability == Capability.SHOPIFY_GET_ARTICLE:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_ARTICLE:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_ARTICLE:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_ARTICLE:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List blogs ─────────────────────────────────────────────────

    def _list_blogs(self, params: dict[str, Any]) -> Any:
        limit, cursor = self._coerce_pagination(params)
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
            if not isinstance(sort_key, str) or sort_key not in _VALID_BLOG_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_BLOG_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_BLOGS_QUERY, variables)
        envelope = data.get("blogs") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        blogs = [
            self._normalise_blog(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_BLOGS,
            data={
                "blogs": blogs,
                "count": len(blogs),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── List articles ──────────────────────────────────────────────

    def _list_articles(self, params: dict[str, Any]) -> Any:
        limit, cursor = self._coerce_pagination(params)
        variables: dict[str, Any] = {"first": limit, "after": cursor}

        # Engines often want articles within a specific blog. Shopify
        # filters this via the search-style query string ("blog_id:N")
        # rather than a dedicated argument.
        query_parts = []
        blog_id = params.get("blog_id") or params.get("blogId")
        if blog_id:
            if not isinstance(blog_id, str):
                raise AdapterValidationError(
                    self.name, "'blog_id' must be a string",
                )
            query_parts.append(f'blog_id:{blog_id.strip()}')

        free_query = params.get("query")
        if free_query is not None:
            if not isinstance(free_query, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            query_parts.append(free_query.strip())

        if query_parts:
            variables["query"] = " ".join(query_parts)

        sort_key = params.get("sort_key")
        if sort_key is not None:
            if not isinstance(sort_key, str) or sort_key not in _VALID_ARTICLE_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_ARTICLE_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_ARTICLES_QUERY, variables)
        envelope = data.get("articles") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        articles = [
            self._normalise_article(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_ARTICLES,
            data={
                "articles": articles,
                "count": len(articles),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        article_id = params.get("id") or params.get("article_id")
        if not isinstance(article_id, str) or not article_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the article) is required",
            )
        data = self._gql(_GET_ARTICLE_QUERY, {"id": article_id.strip()})
        node = data.get("article") or {}
        return self._success(
            Capability.SHOPIFY_GET_ARTICLE,
            data={
                "article": self._normalise_article(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        article_input = self._build_article_input(params, for_update=False)
        data = self._gql(_CREATE_ARTICLE_MUTATION, {"article": article_input})
        self._check_user_errors(data, "articleCreate")
        payload = data.get("articleCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_ARTICLE,
            data={
                "article": self._normalise_article(
                    payload.get("article") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        article_id = params.get("id") or params.get("article_id")
        if not isinstance(article_id, str) or not article_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the article) is required",
            )
        article_input = self._build_article_input(params, for_update=True)
        if not article_input:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (title, body_html, handle, "
                "summary, tags, is_published, author_name, image_url)",
            )
        data = self._gql(_UPDATE_ARTICLE_MUTATION, {
            "id": article_id.strip(),
            "article": article_input,
        })
        self._check_user_errors(data, "articleUpdate")
        payload = data.get("articleUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_ARTICLE,
            data={
                "article": self._normalise_article(
                    payload.get("article") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        article_id = params.get("id") or params.get("article_id")
        if not isinstance(article_id, str) or not article_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the article) is required",
            )
        data = self._gql(_DELETE_ARTICLE_MUTATION, {"id": article_id.strip()})
        self._check_user_errors(data, "articleDelete")
        payload = data.get("articleDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_ARTICLE,
            data={
                "deleted_id": payload.get("deletedArticleId", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _coerce_pagination(self, params: dict[str, Any]) -> tuple[int, str | None]:
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
        return limit, cursor

    def _build_article_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if not for_update:
            blog_id = params.get("blog_id") or params.get("blogId")
            if not isinstance(blog_id, str) or not blog_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'blog_id' is required to create an article",
                )
            out["blogId"] = blog_id.strip()

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
                self.name, "'title' is required to create an article",
            )

        body = params.get("body_html") or params.get("body")
        if body is not None:
            if not isinstance(body, str):
                raise AdapterValidationError(
                    self.name, "'body_html' must be a string",
                )
            out["body"] = body

        summary = params.get("summary")
        if summary is not None:
            if not isinstance(summary, str):
                raise AdapterValidationError(
                    self.name, "'summary' must be a string",
                )
            out["summary"] = summary

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

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    self.name,
                    "'tags' must be a string (comma-separated) or list of strings",
                )
            out["tags"] = tags

        author_name = params.get("author_name") or params.get("authorName")
        if author_name is not None:
            if not isinstance(author_name, str):
                raise AdapterValidationError(
                    self.name, "'author_name' must be a string",
                )
            out["author"] = {"name": author_name}

        image_url = params.get("image_url") or params.get("imageUrl")
        if image_url is not None:
            if not isinstance(image_url, str):
                raise AdapterValidationError(
                    self.name, "'image_url' must be a string",
                )
            alt_text = params.get("image_alt") or params.get("imageAlt") or ""
            out["image"] = {"src": image_url, "altText": alt_text}

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_blog(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "comment_policy": node.get("commentPolicy", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }

    @staticmethod
    def _normalise_article(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        author = node.get("author") or {}
        image = node.get("image") or {}
        blog = node.get("blog") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "body_html": node.get("body", "") or "",
            "summary": node.get("summary", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "is_published": bool(node.get("isPublished", False)),
            "published_at": node.get("publishedAt", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "tags": list(node.get("tags") or []),
            "author_name": (
                author.get("name", "") if isinstance(author, dict) else ""
            ) or "",
            "image_url": (
                image.get("url", "") if isinstance(image, dict) else ""
            ) or "",
            "image_alt": (
                image.get("altText", "") if isinstance(image, dict) else ""
            ) or "",
            "blog_id": (
                blog.get("id", "") if isinstance(blog, dict) else ""
            ) or "",
            "blog_title": (
                blog.get("title", "") if isinstance(blog, dict) else ""
            ) or "",
            "blog_handle": (
                blog.get("handle", "") if isinstance(blog, dict) else ""
            ) or "",
        }
